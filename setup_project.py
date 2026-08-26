import os

base_dir = "/home/ghanasyam/Desktop/S7/flexascale/app"

services = ["frontend", "orders", "inventory", "payments"]

reqs = """fastapi
uvicorn
requests
prometheus-fastapi-instrumentator
"""

dockerfile = """FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 8000
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
"""

frontend_main = """from fastapi import FastAPI, HTTPException
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
"""

orders_main = """from fastapi import FastAPI, HTTPException
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
"""

inventory_main = """from fastapi import FastAPI, HTTPException
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
"""

payments_main = """from fastapi import FastAPI
import time
import random
from prometheus_fastapi_instrumentator import Instrumentator

app = FastAPI(title="Payments Service")

Instrumentator().instrument(app).expose(app)

@app.get("/")
def read_root():
    return {"service": "payments", "status": "ok"}

@app.post("/api/payments/charge")
def charge_payment():
    # Simulate payment gateway latency which can be variable
    latency = random.uniform(0.1, 0.3)
    time.sleep(latency)
    return {"service": "payments", "status": "success", "transaction_id": f"txn_{random.randint(100000, 999999)}"}
"""

mains = {
    "frontend": frontend_main,
    "orders": orders_main,
    "inventory": inventory_main,
    "payments": payments_main
}

for service in services:
    service_dir = os.path.join(base_dir, service)
    os.makedirs(service_dir, exist_ok=True)
    
    with open(os.path.join(service_dir, "requirements.txt"), "w") as f:
        f.write(reqs)
        
    with open(os.path.join(service_dir, "Dockerfile"), "w") as f:
        f.write(dockerfile)
        
    with open(os.path.join(service_dir, "main.py"), "w") as f:
        f.write(mains[service])

print("Successfully created microservices directories and files.")
