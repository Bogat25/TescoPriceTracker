"""The vectorizer embeds only new or changed products and removes stale points."""

import os
import time

import pytest

from stores import embedding_text, semantic, vectorize


class States:
    def __init__(self, docs=()):
        self.docs = {doc["_id"]: dict(doc) for doc in docs}

    def find(self, query, _projection=None):
        return [doc for doc in self.docs.values() if doc["store"] == query["store"]]

    def bulk_write(self, operations, ordered=True):
        for op in operations:
            ref = op._filter["_id"]
            self.docs.setdefault(ref, {"_id": ref}).update(op._doc["$set"])

    def delete_many(self, query):
        for ref in query["_id"]["$in"]:
            self.docs.pop(ref, None)


class Qdrant:
    def __init__(self):
        self.points = {}
        self.deleted = []

    def upsert(self, collection, points):
        for point in points:
            self.points[point.id] = point

    def delete(self, collection, points_selector):
        self.deleted.extend(points_selector.points)


@pytest.fixture
def env(monkeypatch):
    qdrant = Qdrant()
    embedded = []
    monkeypatch.setattr(semantic, "client", lambda: qdrant)

    def embed(texts, mode):
        assert mode == "passage"
        embedded.append(list(texts))
        return [[0.1] * 384 for _ in texts]

    monkeypatch.setattr(semantic, "embed", embed)
    return {"qdrant": qdrant, "embedded": embedded, "monkeypatch": monkeypatch}


def install(env, items, states):
    env["monkeypatch"].setattr(vectorize, "SOURCES", {"tesco": lambda: iter(items)})
    env["monkeypatch"].setattr(vectorize, "state_collection", lambda: states)


def item(ref, text, group=None):
    return ref, text, {"product_id": ref.split(":")[1], "name": text, "category": "Tej", "gtin_norm": None, "group_id": group}


def test_first_pass_embeds_everything_with_store_payload(env):
    states = States()
    install(env, [item("tesco:1", "Tej 1 l"), item("tesco:2", "Kenyér", group="g:599"), item("tesco:3", None)], states)

    counts = vectorize.sync_store("tesco", "e5@rev")

    assert counts == {"embedded": 2, "unchanged": 0, "no_text": 1, "removed": 0}
    point = env["qdrant"].points[semantic.point_id("tesco:2")]
    assert point.payload["ref"] == "tesco:2" and point.payload["store"] == "tesco" and point.payload["group_id"] == "g:599"
    assert states.docs["tesco:1"]["hash"] == vectorize.text_hash("e5@rev", "Tej 1 l")


def test_unchanged_products_are_not_embedded_again(env):
    states = States([{"_id": "tesco:1", "store": "tesco", "hash": vectorize.text_hash("e5@rev", "Tej 1 l")}])
    install(env, [item("tesco:1", "Tej 1 l"), item("tesco:2", "Kenyér")], states)

    counts = vectorize.sync_store("tesco", "e5@rev")

    assert counts["embedded"] == 1 and counts["unchanged"] == 1
    assert env["embedded"] == [["Kenyér"]]


def test_a_new_model_re_embeds_everything(env):
    states = States([{"_id": "tesco:1", "store": "tesco", "hash": vectorize.text_hash("e5@old", "Tej 1 l")}])
    install(env, [item("tesco:1", "Tej 1 l")], states)
    assert vectorize.sync_store("tesco", "e5@new")["embedded"] == 1


def test_products_that_left_the_catalogue_lose_their_point(env):
    states = States([{"_id": "tesco:9", "store": "tesco", "hash": "x"}])
    install(env, [item("tesco:1", "Tej 1 l")], states)

    counts = vectorize.sync_store("tesco", "e5@rev")

    assert counts["removed"] == 1
    assert env["qdrant"].deleted == [semantic.point_id("tesco:9")]
    assert "tesco:9" not in states.docs


def test_batches_are_bounded(env, monkeypatch):
    monkeypatch.setattr(vectorize, "BATCH_SIZE", 2)
    install(env, [item(f"tesco:{i}", f"Termék {i}") for i in range(5)], States())
    vectorize.sync_store("tesco", "e5@rev")
    assert [len(batch) for batch in env["embedded"]] == [2, 2, 1]


def test_failed_pass_is_logged_not_raised(monkeypatch, caplog):
    def down():
        raise semantic.SemanticUnavailable("embedding service: connection refused")

    monkeypatch.setattr(vectorize, "embedding_model", down)
    assert vectorize.run_pass() is False
    assert [r for r in caplog.records if getattr(r, "Action", None) == "vectorize.failed"]


def test_heartbeat_health(tmp_path):
    beat = tmp_path / "beat"
    assert not vectorize.is_alive(str(beat))
    beat.touch()
    assert vectorize.is_alive(str(beat))
    assert not vectorize.is_alive(str(beat), now=time.time() + vectorize.MAX_HEARTBEAT_AGE_SECONDS + 60)


def test_auchan_text_uses_details_when_present():
    text = embedding_text.auchan_text({
        "name": "Auchan zabpehely 500 g", "brand": "Auchan", "category_path": ["Élelmiszer", "Reggeli"],
        "description": "Teljes kiőrlésű zabpehely.", "ingredients": "zab",
    })
    assert text == "Auchan zabpehely 500 g. Márka: Auchan. Kategória: Élelmiszer, Reggeli. Teljes kiőrlésű zabpehely. Összetevők: zab"
    assert embedding_text.auchan_text({"name": "Tej"}) is None


def test_tesco_text_is_bounded():
    text = embedding_text.tesco_text({"name": "Tej", "short_description": "x" * 5000})
    assert len(text) == embedding_text.MAX_CHARS
