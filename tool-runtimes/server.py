"""@input Trusted deployment JSON, model weights and optional API credentials.
@output Isolated YOLO/YOLOv5/MiniMax FastAPI inference service.
@position Model-to-tool adapter. @doc-sync Update INDEX.md on changes.
"""

import argparse
import base64
import json
import os
import uuid
from pathlib import Path
from typing import Literal
import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field


class Detect(BaseModel):
    image_path: str
    confidence: float = Field(default=0.25, ge=0, le=1)
    iou: float = Field(default=0.45, ge=0, le=1)
    image_size: int = Field(default=640, ge=64, le=2048)


class Speech(BaseModel):
    text: str = Field(min_length=1, max_length=10000)
    voice_id: str = "male-qn-qingse"
    model: str = "speech-2.8-hd"
    audio_format: Literal["mp3", "wav"] = "mp3"
    speed: float = Field(default=1, ge=0.5, le=2)


class Picture(BaseModel):
    prompt: str = Field(min_length=1, max_length=10000)
    model: str = "image-01"
    aspect_ratio: str = "1:1"
    prompt_optimizer: bool = True


def create_app(config):
    app = FastAPI(title="Agent Harness Model Tool")
    runtime = config["runtime"]
    output = Path(config["deployment_dir"]) / "outputs"
    output.mkdir(parents=True, exist_ok=True)
    model = None
    if runtime in {"yolo", "yolov5"}:
        weight = Path(config["weights_path"])
        if not weight.is_file():
            raise ValueError("需要有效权重文件")
        if runtime == "yolo":
            from ultralytics import YOLO

            model = YOLO(str(weight))
        else:
            import torch

            repo = Path(config["yolov5_repo"])
            if not (repo / "hubconf.py").is_file():
                raise ValueError("请配置独立 YOLOv5 仓库的绝对路径")
            model = torch.hub.load(
                str(repo),
                "custom",
                path=str(weight),
                source="local",
                device=config.get("device", "cpu"),
            )
    elif runtime != "minimax":
        raise ValueError("自定义模板应提供自己的 Python 脚本")

    @app.get("/health")
    def health():
        return {
            "status": "ok",
            "instance_id": config["instance_id"],
            "runtime": runtime,
        }

    if runtime in {"yolo", "yolov5"}:

        @app.post(
            "/detect",
            description="对本地图片执行检测，返回类别、置信度、边界框和标注图。",
        )
        def detect(body: Detect):
            path = Path(body.image_path).resolve()
            roots = [Path(p).resolve() for p in config.get("input_roots", [])]
            if not any(path.is_relative_to(root) for root in roots):
                raise HTTPException(403, "图片不在允许的输入目录")
            if not path.is_file():
                raise HTTPException(404, "图片不存在")
            target = output / (uuid.uuid4().hex + ".jpg")
            detections = []
            if runtime == "yolo":
                result = model.predict(
                    str(path),
                    conf=body.confidence,
                    iou=body.iou,
                    imgsz=body.image_size,
                    device=config.get("device", "cpu"),
                    verbose=False,
                )[0]
                for box in result.boxes:
                    cls = int(box.cls.item())
                    detections.append(
                        {
                            "class_id": cls,
                            "label": result.names[cls],
                            "confidence": float(box.conf.item()),
                            "bbox": box.xyxy[0].tolist(),
                        }
                    )
                result.save(filename=str(target))
            else:
                from PIL import Image

                model.conf = body.confidence
                model.iou = body.iou
                result = model(str(path), size=body.image_size)
                for x1, y1, x2, y2, conf, cls in result.xyxy[0].cpu().tolist():
                    detections.append(
                        {
                            "class_id": int(cls),
                            "label": model.names[int(cls)],
                            "confidence": conf,
                            "bbox": [x1, y1, x2, y2],
                        }
                    )
                Image.fromarray(result.render()[0]).save(target)
            return {
                "ok": True,
                "detections": detections,
                "count": len(detections),
                "annotated_image_path": str(target),
            }
    else:
        key = os.environ.get("AGENT_TOOL_API_KEY", "")
        base = (
            config.get("base_url", "https://api.minimax.chat")
            .rstrip("/")
            .removesuffix("/v1")
        )

        async def request(path, payload):
            if not key:
                raise HTTPException(400, "推理模板尚未配置 API 密钥")
            async with httpx.AsyncClient(timeout=120, trust_env=False) as client:
                response = await client.post(
                    base + path,
                    json=payload,
                    headers={"Authorization": "Bearer " + key},
                )
                response.raise_for_status()
                data = response.json()
            error = data.get("base_resp", {})
            if error.get("status_code", 0) not in (0, "0"):
                raise HTTPException(
                    502,
                    str(error.get("status_msg", "上游错误")).replace(key, "[REDACTED]"),
                )
            return data

        @app.post("/tts/synthesize", description="使用 MiniMax 将文本合成为本地音频。")
        async def speech(body: Speech):
            data = await request(
                "/v1/t2a_v2",
                {
                    "model": body.model,
                    "text": body.text,
                    "stream": False,
                    "voice_setting": {"voice_id": body.voice_id, "speed": body.speed},
                    "audio_setting": {"format": body.audio_format},
                    "output_format": "hex",
                },
            )
            audio = data.get("data", {}).get("audio")
            if not audio:
                raise HTTPException(502, "上游未返回音频")
            target = output / (uuid.uuid4().hex + "." + body.audio_format)
            target.write_bytes(bytes.fromhex(audio))
            return {"ok": True, "audio_path": str(target)}

        @app.post(
            "/images/generate", description="使用 MiniMax 生成图片并保存本地文件。"
        )
        async def picture(body: Picture):
            data = await request(
                "/v1/image_generation",
                {**body.model_dump(), "response_format": "base64"},
            )
            images = data.get("data", {}).get("image_base64", [])
            if isinstance(images, str):
                images = [images]
            if not images:
                raise HTTPException(502, "上游未返回 base64 图片")
            paths = []
            for item in images[:4]:
                target = output / (uuid.uuid4().hex + ".png")
                target.write_bytes(base64.b64decode(item.split(",")[-1], validate=True))
                paths.append(str(target))
            return {"ok": True, "image_path": paths[0], "image_paths": paths}

    return app


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    import uvicorn

    uvicorn.run(create_app(config), host="127.0.0.1", port=int(config["port"]))
