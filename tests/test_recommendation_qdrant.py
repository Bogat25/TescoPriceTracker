import importlib.util
from pathlib import Path
from types import SimpleNamespace


REPO_ROOT = Path(__file__).resolve().parent.parent


def _load_recommendation_engine():
    module_path = REPO_ROOT / "backend-api" / "recommendation_engine.py"
    spec = importlib.util.spec_from_file_location("backend_recommendation_engine", module_path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_category_search_uses_current_qdrant_query_points_api(monkeypatch):
    engine = _load_recommendation_engine()

    class FakeQdrant:
        def __init__(self):
            self.query_kwargs = None

        def retrieve(self, **_kwargs):
            return [
                SimpleNamespace(vector=[1.0, 0.0]),
                SimpleNamespace(vector=[0.0, 1.0]),
            ]

        def query_points(self, **kwargs):
            self.query_kwargs = kwargs
            return SimpleNamespace(
                points=[
                    SimpleNamespace(payload={"product_id": "keep"}, score=0.91),
                    SimpleNamespace(payload={"product_id": "excluded"}, score=0.88),
                ]
            )

    client = FakeQdrant()
    monkeypatch.setattr(engine, "_get_qdrant", lambda: client)

    results = engine.search_category_bucket(
        category="Bakery",
        alerted_product_ids=["alerted-product"],
        slot_size=2,
        exclude_ids={"excluded"},
    )

    assert results == [{"product_id": "keep", "score": 0.91}]
    assert client.query_kwargs["query"] == [0.5, 0.5]
    assert client.query_kwargs["limit"] == 5
    assert client.query_kwargs["with_payload"] is True
