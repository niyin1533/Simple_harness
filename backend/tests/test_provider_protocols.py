"""@input Mock HTTP providers and memory rows. @output JSON and embedding adapter regression checks.
@position Provider protocol verification. @doc-sync Update tests/INDEX.md on changes.
"""

import json
from types import SimpleNamespace
import httpx
import pytest
from app import providers, governance


@pytest.mark.parametrize(
    "provider,key,value",
    [
        ("openai-compatible", "response_format", {"type": "json_object"}),
        ("ollama", "format", "json"),
    ],
)
@pytest.mark.asyncio
async def test_json_mode(monkeypatch, provider, key, value):
    requests = []

    def respond(request):
        requests.append(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "message": {"content": "{}"},
                "choices": [{"message": {"content": "{}"}, "finish_reason": "stop"}],
            },
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(respond)),
    )
    model = {
        "config": {
            "provider": provider,
            "endpoint": "http://fixture",
            "model": "fixture",
        }
    }
    await providers.complete(model, [], json_mode=True)
    await providers.complete(model, [])
    assert requests[0][key] == value
    assert key not in requests[1]


@pytest.mark.parametrize(
    "endpoint,provider,path,native",
    [
        ("http://localhost:11434", "auto", "/api/embed", True),
        ("http://localhost:11434/v1", "auto", "/v1/embeddings", False),
        ("http://localhost:11434/api/embed", "auto", "/api/embed", True),
        ("http://fixture/api", "ollama", "/api/embed", True),
        ("http://fixture/v1/embeddings", "openai-compatible", "/v1/embeddings", False),
    ],
)
@pytest.mark.asyncio
async def test_embedding_protocol(monkeypatch, endpoint, provider, path, native):
    def respond(request):
        assert request.url.path == path
        assert json.loads(request.content) == {
            "model": "bge-m3:latest",
            "input": "test",
        }
        return httpx.Response(
            200,
            json={"embeddings": [[0.1, 0.2]]}
            if native
            else {"data": [{"embedding": [0.1, 0.2]}]},
        )

    client = httpx.AsyncClient
    monkeypatch.setattr(
        providers.httpx,
        "AsyncClient",
        lambda **kwargs: client(transport=httpx.MockTransport(respond)),
    )
    assert await providers.embedding(
        {
            "embedding_endpoint": endpoint,
            "embedding_provider": provider,
            "embedding_model": "bge-m3:latest",
        },
        "test",
    ) == [0.1, 0.2]


@pytest.mark.asyncio
async def test_recall_falls_back_and_skips_empty(monkeypatch):
    calls = []

    async def broken(*args):
        calls.append(True)
        raise ValueError("bad embedding")

    class DB:
        rows = []

        async def get(self, *args):
            return SimpleNamespace(config={}, secret=None)

        async def scalars(self, *args):
            return SimpleNamespace(all=lambda: self.rows)

    db = DB()
    monkeypatch.setattr(governance, "embedding", broken)
    monkeypatch.setattr(governance, "public", lambda row: {"content": row.content})
    assert await governance.retrieve(db, "u", "a", "hello", ["user"]) == []
    assert not calls
    db.rows = [SimpleNamespace(agent_id=None, content="hello", vector=[1])]
    assert await governance.retrieve(db, "u", "a", "hello", ["user"]) == [
        {"content": "hello"}
    ]
    assert len(calls) == 1
