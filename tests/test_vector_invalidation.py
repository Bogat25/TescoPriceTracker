from mongo import database_manager as db


def test_embedding_source_change_marks_existing_vector_stale(monkeypatch):
    original = {
        "_id": "123",
        "tpnc": "123",
        "name": "Old name",
        "vector_embedding": True,
        "needs_revector": False,
        "price_history": [],
    }
    saved = {}
    monkeypatch.setattr(db, "load_product_data", lambda _: dict(original))
    monkeypatch.setattr(db, "save_product_data", lambda _, data: saved.update(data))

    db.insert_daily_prices(
        "123",
        [("normal", {"price": 10, "unit_price": 10, "unit_measure": "each"})],
        metadata={"name": "New name"},
    )

    assert saved["needs_revector"] is True


def test_price_only_change_keeps_existing_vector_current(monkeypatch):
    original = {
        "_id": "123",
        "tpnc": "123",
        "name": "Same name",
        "vector_embedding": True,
        "needs_revector": False,
        "price_history": [],
    }
    saved = {}
    monkeypatch.setattr(db, "load_product_data", lambda _: dict(original))
    monkeypatch.setattr(db, "save_product_data", lambda _, data: saved.update(data))

    db.insert_daily_prices(
        "123",
        [("normal", {"price": 12, "unit_price": 12, "unit_measure": "each"})],
        metadata=None,
    )

    assert saved["needs_revector"] is False
