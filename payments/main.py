from fastapi import FastAPI
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
