"""@input Model configuration and HTTPX. @output JSON-mode chat and native/compatible embeddings.
@position LLM adapters. @doc-sync Update header and INDEX.md on changes.
"""

import json
import math
from urllib.parse import urlsplit, urlunsplit
import httpx
from .security import decrypt


def parse_json(text):
    value = text.strip()
    if value.startswith("```"):
        value = "\n".join(value.splitlines()[1:-1])
    start, end = value.find("{"), value.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("模型未返回有效 JSON 对象")
    return json.loads(value[start : end + 1])


async def complete(model, messages, *, json_mode=False):
    config = model["config"]
    endpoint = config.get("endpoint", "").rstrip("/")
    headers = {}
    key = decrypt(model.get("secret"))
    if key:
        headers["Authorization"] = "Bearer " + key
    limit = int(config.get("max_output_tokens", 2048))
    if config.get("provider") == "ollama":
        path = "/api/chat"
        payload = {
            "model": config["model"],
            "messages": messages,
            "stream": False,
            "options": {"num_predict": limit},
        }
    else:
        path = "/chat/completions"
        payload = {"model": config["model"], "messages": messages, "max_tokens": limit}
    if "temperature" in config:
        if path == "/api/chat":
            payload["options"]["temperature"] = float(config["temperature"])
        else:
            payload["temperature"] = float(config["temperature"])
    if json_mode:
        if urlsplit(endpoint).hostname == "api.deepseek.com":
            payload["thinking"] = {"type": "disabled"}
        if path == "/api/chat":
            payload["format"] = "json"
        else:
            payload["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(120, connect=20), trust_env=False
    ) as client:
        response = await client.post(endpoint + path, json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()
    content = (
        data.get("message", {}).get("content")
        if path == "/api/chat"
        else data["choices"][0]["message"].get("content")
    )
    if not isinstance(content, str) or not content.strip():
        raise ValueError("模型未返回文本内容")
    return {
        "content": content,
        "finish_reason": data.get("done_reason")
        if path == "/api/chat"
        else data["choices"][0].get("finish_reason"),
        "usage": data.get(
            "usage",
            {
                "prompt_tokens": data.get("prompt_eval_count"),
                "completion_tokens": data.get("eval_count"),
            },
        ),
    }


async def structured(model, messages, validate):
    """Bounded JSON correction for governance; never interprets reasoning as output."""
    for attempt in range(2):
        try:
            reply = await complete(model, messages, json_mode=True)
            if reply.get("finish_reason") == "length":
                raise ValueError("治理输出超过 token 限额，请增大模型输出长度")
            value = parse_json(reply["content"])
            validate(value)
            return value
        except ValueError:
            if attempt:
                raise
            messages = messages + [
                {
                    "role": "user",
                    "content": "上次输出为空或未通过格式校验。请严格按要求返回完整 JSON 对象，字段、类型和目标 ID 必须有效，不要输出思考过程。",
                }
            ]


def embedding_target(config):
    parts = urlsplit(config["embedding_endpoint"].strip().rstrip("/"))
    if parts.scheme not in {"http", "https"} or not parts.hostname:
        raise ValueError("Embedding API 地址必须为 HTTP/HTTPS")
    provider = config.get("embedding_provider") or "auto"
    if provider not in {"auto", "ollama", "openai-compatible"}:
        raise ValueError("未知 Embedding 接口类型")
    path = parts.path.rstrip("/")
    native = provider == "ollama" or (
        provider == "auto"
        and (
            path.endswith(("/api", "/api/embed")) or (parts.port == 11434 and not path)
        )
    )
    if native:
        for suffix in ("/api/embed", "/api", "/v1/embeddings", "/v1"):
            if path.endswith(suffix):
                path = path[: -len(suffix)]
                break
        path += "/api/embed"
    elif not path.endswith("/embeddings"):
        path += "/embeddings"
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, "")), native


async def embedding(config, text, secret=None):
    if not config.get("embedding_endpoint") or not config.get("embedding_model"):
        return None
    headers = {"Authorization": "Bearer " + decrypt(secret)} if secret else {}
    endpoint, native = embedding_target(config)
    async with httpx.AsyncClient(timeout=60, trust_env=False) as client:
        response = await client.post(
            endpoint,
            json={"model": config["embedding_model"], "input": text},
            headers=headers,
        )
        response.raise_for_status()
        data = response.json()
        try:
            vector = data["embeddings"][0] if native else data["data"][0]["embedding"]
            if (
                not isinstance(vector, list)
                or not vector
                or any(
                    isinstance(v, bool)
                    or not isinstance(v, (int, float))
                    or not math.isfinite(v)
                    for v in vector
                )
            ):
                raise ValueError()
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(
                "Embedding 返回的向量格式无效，请检查接口类型和模型"
            ) from exc
        return vector
