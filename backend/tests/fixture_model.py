"""@input Local test-only model requests. @output Deterministic OpenAI-compatible responses.
@position End-to-end fixture; never seeded as a platform model. @doc-sync Update INDEX.md on changes.
"""

from fastapi import FastAPI

app = FastAPI()


@app.post("/v1/chat/completions")
async def completion(body: dict):
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "端到端链路验证通过。"}}
        ],
        "usage": {"prompt_tokens": 10, "completion_tokens": 10},
    }
