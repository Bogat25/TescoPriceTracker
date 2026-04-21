"""Import old JSON files into MongoDB, merging with any existing data.

Safe to run before or after today's scrape:
- Products not in MongoDB: full insert (format-converted to daily snapshots).
- Products already in MongoDB: only adds days from the JSON that are missing;
  never overwrites existing daily entries (today's fresh scrape is preserved).
- Metadata (name, image, etc.) is only set if the field is absent in MongoDB.

Usage:
  python scripts/import_json_merge.py --folder /path/to/json/files
  python scripts/import_json_merge.py --folder /path/to/json/files --dry-run
"""

import argparse
import glob
import json
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from pymongo import MongoClient
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION

METADATA_FIELDS = ("name", "unit_of_measure", "default_image_url", "pack_size_value", "pack_size_unit")
BATCH_SIZE = 200


def date_range(start_str, end_str):
    try:
        start = datetime.strptime(start_str, "%Y-%m-%d").date()
        end = datetime.strptime(end_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return
    current = start
    while current <= end:
        yield current.isoformat()
        current += timedelta(days=1)


def _strip_period_keys(fields):
    return {k: v for k, v in fields.items() if k not in ("start_date", "end_date")}


def json_to_daily(raw_history):
    """Convert old period-dict format to {date: {normal, discount, clubcard}} map."""
    if not isinstance(raw_history, dict):
        return {}
    daily = {}
    for category in ("normal", "discount", "clubcard"):
        for period in raw_history.get(category, []):
            start = period.get("start_date")
            end = period.get("end_date")
            if not start or not end:
                continue
            fields = _strip_period_keys(period)
            for day in date_range(start, end):
                if day not in daily:
                    daily[day] = {"date": day, "normal": None, "discount": None, "clubcard": None}
                daily[day][category] = fields
    return daily


def import_and_merge(folder, dry_run=False):
    client = MongoClient(MONGO_URI)
    collection = client[MONGO_DB_NAME][MONGO_COLLECTION]

    files = sorted(glob.glob(os.path.join(folder, "*.json")))
    files = [f for f in files if os.path.basename(f)[0].isdigit()]

    print(f"Found {len(files)} JSON files in {folder}")
    if dry_run:
        print("DRY RUN — no writes.\n")

    inserted = 0
    merged = 0
    skipped = 0
    errors = 0

    for fpath in files:
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                doc = json.load(f)
        except Exception as e:
            print(f"  ERROR reading {fpath}: {e}")
            errors += 1
            continue

        tpnc = str(doc.get("tpnc", ""))
        if not tpnc:
            errors += 1
            continue

        raw_history = doc.get("price_history", {})

        # Convert JSON's period format → daily map
        json_daily = json_to_daily(raw_history)
        if not json_daily:
            skipped += 1
            continue

        existing = collection.find_one({"_id": tpnc}, {"price_history": 1, "last_scraped_price": 1})

        if existing is None:
            # New product: insert fresh
            new_doc = {
                "_id": tpnc,
                "tpnc": tpnc,
                "price_history": [json_daily[d] for d in sorted(json_daily)],
            }
            for field in METADATA_FIELDS:
                if doc.get(field) is not None:
                    new_doc[field] = doc[field]
            new_doc["last_scraped_price"] = doc.get("last_scraped_price", "")

            if not dry_run:
                collection.insert_one(new_doc)
            inserted += 1

        else:
            # Existing product: merge missing days only
            existing_history = existing.get("price_history", [])

            # Build set of dates already in MongoDB
            existing_dates = {e["date"] for e in existing_history if isinstance(e, dict) and "date" in e}

            # Only keep days from JSON that are not already in MongoDB
            new_days = [json_daily[d] for d in sorted(json_daily) if d not in existing_dates]

            if not new_days:
                skipped += 1
                continue

            # Merge: insert missing days, re-sort by date
            merged_history = existing_history + new_days
            merged_history.sort(key=lambda e: e.get("date", ""))

            # Use the more recent last_scraped_price
            existing_lsp = existing.get("last_scraped_price", "")
            json_lsp = doc.get("last_scraped_price", "")
            keep_lsp = max(existing_lsp, json_lsp)  # ISO strings compare correctly

            update = {"$set": {"price_history": merged_history, "last_scraped_price": keep_lsp}}

            # Set metadata only if missing from existing doc
            for field in METADATA_FIELDS:
                if doc.get(field) is not None:
                    update["$setOnInsert"] = update.get("$setOnInsert", {})
                # Use $set only if field not present; simpler: just check existing doc
            existing_full = collection.find_one({"_id": tpnc}, {f: 1 for f in METADATA_FIELDS}) or {}
            for field in METADATA_FIELDS:
                if existing_full.get(field) is None and doc.get(field) is not None:
                    update["$set"][field] = doc[field]

            if not dry_run:
                collection.update_one({"_id": tpnc}, update)

            if dry_run and (inserted + merged) < 3:
                print(f"  TPNC {tpnc} ({doc.get('name', '?')[:40]})")
                print(f"    Existing days in DB: {len(existing_dates)}, new days to add: {len(new_days)}")
                if new_days:
                    print(f"    Sample new day: {new_days[0]}")
                print()

            merged += 1

    print(f"\nDone.  Inserted (new): {inserted}  |  Merged (added days): {merged}  |  Skipped (no new days): {skipped}  |  Errors: {errors}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge old JSON files into MongoDB")
    parser.add_argument("--folder", required=True, help="Path to the folder containing *.json files")
    parser.add_argument("--dry-run", action="store_true", help="Preview without writing")
    args = parser.parse_args()
    import_and_merge(args.folder, dry_run=args.dry_run)
