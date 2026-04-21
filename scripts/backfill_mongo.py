import glob
import json
import os
from pymongo import MongoClient, UpdateOne
from config import MONGO_URI, MONGO_DB_NAME, MONGO_COLLECTION, DATA_DIR

def backfill():
    client = MongoClient(MONGO_URI)
    db = client[MONGO_DB_NAME]
    collection = db[MONGO_COLLECTION]

    files = glob.glob(os.path.join(DATA_DIR, "*.json"))
    operations = []
    processed = 0

    for fpath in files:
        basename = os.path.basename(fpath)
        if not basename[0].isdigit():
            continue
        try:
            with open(fpath, 'r', encoding='utf-8') as f:
                data = json.load(f)
                tpnc = data.get('tpnc')
                if tpnc:
                    # Using tpnc as _id
                    data['_id'] = tpnc
                    operations.append(UpdateOne({'_id': tpnc}, {'$set': data}, upsert=True))
                    processed += 1
        except Exception as e:
            print(f"Error processing {fpath}: {e}")

    if operations:
        collection.bulk_write(operations)
    
    print(f"Backfilled {processed} products to MongoDB.")

if __name__ == '__main__':
    backfill()
