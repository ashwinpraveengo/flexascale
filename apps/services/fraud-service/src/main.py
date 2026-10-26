"""Fraud Service: risk-scores a checkout before payment.

Leaf service. Called by order-service during checkout (required step). The
score is a small fixed logistic model over hashed features; only obviously
abusive orders are blocked, so normal load-test traffic passes.
"""
import hashlib
import math
import os
from typing import List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "fraud-service")
BLOCK_THRESHOLD = float(os.getenv("FRAUD_BLOCK_THRESHOLD", "0.98"))

app = FastAPI(title="Fraud Detection Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

N_FEATURES = 256
# Fixed pseudo-random weights (a stand-in for a trained model).
WEIGHTS = [((hashlib.sha256(f"w{i}".encode()).digest()[0] / 255.0) - 0.5) * 0.4 for i in range(N_FEATURES)]


class FraudItem(BaseModel):
    product_id: int
    quantity: int = 1


class FraudRequest(BaseModel):
    user_id: int
    amount: float
    card_number: str = ""
    items: List[FraudItem] = []


def _features(req: FraudRequest) -> List[float]:
    x = [0.0] * N_FEATURES
    tokens = [f"user:{req.user_id}", f"bin:{req.card_number[:6]}", f"amt:{int(req.amount // 50)}"]
    tokens += [f"item:{it.product_id}:{min(it.quantity, 5)}" for it in req.items]
    for t in tokens:
        h = hashlib.sha256(t.encode()).digest()
        for _ in range(30):
            h = hashlib.sha256(h).digest()
        x[int.from_bytes(h[:2], "big") % N_FEATURES] += 1.0
    return x


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/api/fraud/check")
def check(req: FraudRequest):
    x = _features(req)
    z = -4.0 + sum(w * v for w, v in zip(WEIGHTS, x)) + 0.0008 * max(0.0, req.amount - 10000)
    score = 1.0 / (1.0 + math.exp(-z))
    return {"score": round(score, 4), "approved": score < BLOCK_THRESHOLD, "threshold": BLOCK_THRESHOLD}
