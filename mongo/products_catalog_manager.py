from datetime import datetime
import logging

from mongo.database_manager import get_db

logger = logging.getLogger(__name__)

_catalog_coll = None


def get_catalog_collection():
    global _catalog_coll
    if _catalog_coll is None:
        coll = get_db()
        db = coll.database
        _catalog_coll = db["products_catalog"]
        _catalog_coll.create_index("tpnc", unique=True)
        _catalog_coll.create_index([("last_seen", -1)])
    return _catalog_coll


def upsert_product_catalog(metadata: dict) -> bool:
    tpnc = str(metadata.get("tpnc") or metadata.get("_id", ""))
    if not tpnc:
        return False

    coll = get_catalog_collection()
    doc = {
        "tpnc": tpnc,
        "name": metadata.get("name"),
        "brand_name": metadata.get("brand_name"),
        "default_image_url": metadata.get("default_image_url"),
        "super_department_name": metadata.get("super_department_name"),
        "department_name": metadata.get("department_name"),
        "aisle_name": metadata.get("aisle_name"),
        "shelf_name": metadata.get("shelf_name"),
        "tpnb": metadata.get("tpnb"),
        "gtin": metadata.get("gtin"),
        "last_seen": datetime.utcnow(),
    }
    doc = {k: v for k, v in doc.items() if v is not None}

    result = coll.update_one(
        {"tpnc": tpnc},
        {"$set": doc},
        upsert=True,
    )
    return result.upserted_id is not None


def iter_changed_since(since: datetime, limit: int = 1000, offset: int = 0):
    coll = get_catalog_collection()
    cursor = (
        coll.find({"last_seen": {"$gte": since}})
        .sort("last_seen", 1)
        .skip(offset)
        .limit(limit)
    )
    for doc in cursor:
        doc.pop("_id", None)
        yield doc
