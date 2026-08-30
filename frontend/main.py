from fastapi import FastAPI, HTTPException
import requests
import os
import time
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Frontend API Gateway")

# Instrument with Prometheus
Instrumentator().instrument(app).expose(app)

ORDERS_URL = os.getenv("ORDERS_URL", "http://localhost:8001")

@app.get("/")
def read_root():
    return {"service": "frontend", "status": "ok"}

@app.post("/api/checkout")
def checkout():
    # Simulate processing time
    time.sleep(0.05)
    try:
        response = requests.post(f"{ORDERS_URL}/api/orders")
        response.raise_for_status()
        return {"service": "frontend", "message": "Checkout successful", "order_data": response.json()}
    except requests.exceptions.RequestException as e:
        raise HTTPException(status_code=500, detail=f"Failed to communicate with orders service: {str(e)}")
