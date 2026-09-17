"""Tesco documents seen through the store-neutral layer, and the GTIN key."""

from mongo import database_manager as db
from stores import tesco


DOC = {
    "_id": "121262922",
    "tpnc": "121262922",
    "name": "Coca-Cola colaízű szénsavas üdítőital 300 ml",
    "gtin": "00000054026193",
    "brand_name": "COCA-COLA",
    "default_image_url": "https://img/1.jpg",
    "super_department_name": "Italok",
    "department_name": "Üdítők",
    "aisle_name": None,
    "pack_size_value": "0.3",
    "pack_size_unit": "l",
    "last_scraped_price": "2026-09-17T05:12:00",
    "browse_sort": {"details": {"last_scraped_price": 295, "clubcard_price": 249,
                                "unit_price": 983.3, "unit_measure": "l"}},
    "price_history": [
        {"date": "2026-09-16", "normal": {"price": 295, "unit_price": 983.3, "unit_measure": "l"},
         "discount": None, "clubcard": None},
        {"date": "2026-09-17", "normal": {"price": 295, "unit_price": 983.3, "unit_measure": "l"},
         "discount": {"price": 269}, "clubcard": {"price": 249}},
    ],
}


def test_offer_maps_tesco_fields():
    offer = tesco.offer_from_doc(DOC)
    assert offer["ref"] == "tesco:121262922"
    assert offer["gtin"] == "54026193"
    assert offer["is_weighed"] is False
    assert offer["brand"] == "COCA-COLA"
    assert offer["category_path"] == ["Italok", "Üdítők"]
    assert offer["pack_size"] == 0.3 and offer["pack_unit"] == "l"
    assert offer["prices"] == {"regular": 295.0, "promo": None, "loyalty": 249.0, "unit_price": 983.3, "unit": "l"}
    assert offer["effective_price"] == 249.0
    assert offer["price_date"] == "2026-09-17"
    assert offer["url"] == "https://bevasarlas.tesco.hu/shop/hu-HU/products/121262922"
    assert offer["availability"] == "available"


def test_offer_without_denormalised_prices_reads_history():
    doc = {k: v for k, v in DOC.items() if k != "browse_sort"}
    offer = tesco.offer_from_doc(doc)
    assert offer["prices"]["promo"] == 269.0
    assert offer["prices"]["loyalty"] == 249.0


def test_history_uses_neutral_price_names_in_date_order():
    doc = dict(DOC, price_history=list(reversed(DOC["price_history"])) + ["bad", {"normal": {}}])
    rows = tesco.history_from_doc(doc)
    assert [row["date"] for row in rows] == ["2026-09-16", "2026-09-17"]
    assert rows[1] == {"date": "2026-09-17", "regular": 295.0, "promo": 269.0, "loyalty": 249.0,
                       "unit_price": 983.3, "unit": "l", "availability": None}


def test_in_store_weighed_code_is_flagged():
    offer = tesco.offer_from_doc(dict(DOC, gtin="2802590000000"))
    assert offer["is_weighed"] is True


class BulkCollection:
    def __init__(self, docs):
        self.docs = docs
        self.operations = []

    def find(self, query, projection):
        assert query == {"gtin": {"$exists": True}, "gtin_norm": {"$exists": False}}
        return iter(self.docs)

    def bulk_write(self, operations, ordered):
        self.operations.extend(operations)
        return type("Result", (), {"modified_count": len(operations)})()


def test_gtin_backfill_batches_and_skips_unusable_codes():
    coll = BulkCollection([{"_id": "1", "gtin": "00000054026193"}, {"_id": "2", "gtin": ""},
                           {"_id": "3", "gtin": "5998200485596"}])
    assert db.backfill_gtin_norm(coll, batch_size=1) == 2
    assert [op._doc for op in coll.operations] == [{"$set": {"gtin_norm": "54026193"}},
                                                  {"$set": {"gtin_norm": "5998200485596"}}]


def test_scraper_writes_normalised_gtin(monkeypatch):
    saved = {}
    monkeypatch.setattr(db, "load_product_data", lambda _tpnc: None)
    monkeypatch.setattr(db, "save_product_data", lambda tpnc, data: saved.update(data))
    db.insert_daily_prices("121262922", [("normal", {"price": 295})], metadata={"gtin": "00000054026193"})
    assert saved["gtin_norm"] == "54026193"
