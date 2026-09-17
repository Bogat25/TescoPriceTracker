"""Embedding service API, with the model replaced by a fake (no torch needed)."""

import importlib.util
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


class Matrix(list):
    """Stands in for the numpy array sentence-transformers returns (CI has no numpy)."""

    def tolist(self):
        return list(self)


SERVICE_DIR = Path(__file__).resolve().parents[1] / "embedding-service"


@pytest.fixture
def service(monkeypatch):
    monkeypatch.syspath_prepend(str(SERVICE_DIR))
    spec = importlib.util.spec_from_file_location("embedding_service_app", SERVICE_DIR / "app.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    class FakeModel:
        def __init__(self):
            self.seen = []

        def encode(self, texts, **_kwargs):
            self.seen.append(list(texts))
            return Matrix([[1.0] * 384 for _ in texts])

    model = FakeModel()
    module._state.update(model=model, dimension=384)
    yield module, model
    sys.modules.pop("logging_setup", None)


def test_adds_the_e5_prefix_for_the_role(service):
    module, model = service
    client = TestClient(module.app)  # no context manager: the real model is not loaded

    response = client.post("/embed", json={"texts": ["  gluténmentes   kenyér "], "mode": "query"})

    assert response.status_code == 200
    assert model.seen == [["query: gluténmentes kenyér"]]
    body = response.json()
    assert body["dimension"] == 384 and len(body["vectors"]) == 1

    client.post("/embed", json={"texts": ["Tej 1 l"], "mode": "passage"})
    assert model.seen[-1] == ["passage: Tej 1 l"]


def test_large_batches_are_encoded_in_chunks(service):
    """A search must not wait for a whole indexing batch: the lock is per chunk."""
    module, model = service
    client = TestClient(module.app)

    response = client.post("/embed", json={"texts": ["Tej 1 l"] * 40, "mode": "passage"})

    assert len(response.json()["vectors"]) == 40
    assert [len(seen) for seen in model.seen] == [module.CHUNK, module.CHUNK, 8]


def test_rejects_unknown_modes_and_oversized_batches(service):
    module, _ = service
    client = TestClient(module.app)
    assert client.post("/embed", json={"texts": ["x"], "mode": "document"}).status_code == 422
    assert client.post("/embed", json={"texts": ["x"] * (module.MAX_TEXTS + 1), "mode": "passage"}).status_code == 422


def test_health_waits_for_the_model(service):
    module, _ = service
    client = TestClient(module.app)
    assert client.get("/health").status_code == 200
    module._state["model"] = None
    assert client.get("/health").status_code == 503
    assert client.post("/embed", json={"texts": ["x"], "mode": "query"}).status_code == 503
