from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import database_manager as db
import uvicorn

app = FastAPI(title="Tesco Price Tracker API", version="1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)

@app.on_event("startup")
def startup_event():
    db.init_db()

@app.get("/health")
def health_check():
    return {"status": "ok"}

@app.get("/{tpnc}.json")
def get_legacy_product_json(tpnc: str):
    """Compatibility shim for the existing browser extension"""
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    
    if "_id" in prod:
        del prod["_id"]
    return prod

@app.get("/api/v1/products/{tpnc}")
def get_product(tpnc: str):
    prod = db.get_product(tpnc)
    if not prod:
        raise HTTPException(status_code=404, detail="Product not found")
    if "_id" in prod:
        del prod["_id"]
    return prod

if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=5000)
