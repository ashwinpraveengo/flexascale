from fastapi import FastAPI, HTTPException
import requests
import os
import time
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Inventory Service")

Instrumentator().instrument(app).expose(app)

PAYMENTS_URL = os.getenv("PAYMENTS_URL", "http://localhost:8003")

@app.get("/")
def read_root():
    return {"service": "inventory", "status": "ok"}

@app.post("/api/inventory/reserve")
def reserve_inventory():
    time.sleep(0.06) # Simulate DB query latency
    
    try:
        response = requests.post(f"{PAYMENTS_URL}/api/payments/charge")
        response.raise_for_status()
        return {"service": "inventory", "status": "reserved", "payment_data": response.json()}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with payments service: {str(e)}")
