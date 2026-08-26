from fastapi import FastAPI, HTTPException
import requests
import os
import time
import random
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Orders Service")

Instrumentator().instrument(app).expose(app)

INVENTORY_URL = os.getenv("INVENTORY_URL", "http://localhost:8002")

@app.get("/")
def read_root():
    return {"service": "orders", "status": "ok"}

@app.post("/api/orders")
def create_order():
    # Simulate CPU intensive task for orders (e.g. payload parsing, validation)
    for _ in range(10000):
        pass
    time.sleep(0.08) # Artificial delay
    
    try:
        response = requests.post(f"{INVENTORY_URL}/api/inventory/reserve")
        response.raise_for_status()
        return {"service": "orders", "order_id": random.randint(1000, 9999), "inventory_data": response.json()}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with inventory service: {str(e)}")
