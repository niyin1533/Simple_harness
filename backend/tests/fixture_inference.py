"""@input Test deployment protocol. @output Health/OpenAPI and deterministic image analysis metadata.
@position Deployment fixture, not a real ML model. @doc-sync Update INDEX.md on changes.
"""

import argparse
import json
from pathlib import Path
from fastapi import FastAPI
from pydantic import BaseModel
import uvicorn

parser = argparse.ArgumentParser()
parser.add_argument("--config")
args = parser.parse_args()
config = json.loads(Path(args.config).read_text())
app = FastAPI()


class Input(BaseModel):
    image_path: str


@app.get("/health")
def health():
    return {"instance_id": config["instance_id"], "status": "ok"}


@app.post("/detect")
def detect(body: Input):
    return {
        "ok": True,
        "input_exists": Path(body.image_path).is_file(),
        "detections": [],
    }


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=config["port"])
