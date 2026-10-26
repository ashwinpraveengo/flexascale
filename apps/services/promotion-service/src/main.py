"""Promotion Service: evaluates the active promotion rules for a set of products.

Leaf service (no downstream calls). Rules are evaluated per request, so the
CPU cost grows with the number of products asked about.
"""
import hashlib
import os
import time
from typing import List, Optional
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware

from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "promotion-service")

app = FastAPI(title="Promotion Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

# Static rule set: (rule id, product predicate modulus, remainder, percent off, label)
RULES = [
    ("WEEKLY-ELECTRONICS", 7, 1, 10, "10% off selected electronics"),
    ("BUNDLE-3", 5, 2, 5, "5% off when bought with accessories"),
    ("CLEARANCE", 11, 3, 20, "Clearance: 20% off"),
    ("LOYALTY", 3, 0, 3, "Loyalty member price"),
    ("FLASH", 13, 1, 15, "Flash deal"),
]


def _eligible(product_id: int, rule: tuple, hour: int) -> bool:
    # Hash the (rule, product, hour) triple so eligibility rotates over the day,
    # the way a real campaign calendar would.
    rid, mod, rem, _, _ = rule
    digest = hashlib.sha256(f"{rid}:{product_id}:{hour}".encode()).digest()
    for _ in range(40):
        digest = hashlib.sha256(digest).digest()
    return (product_id % mod == rem) or digest[0] < 24


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/api/promotions/active")
def active_promotions(product_ids: Optional[str] = Query(None, description="Comma-separated product ids")):
    ids: List[int] = []
    if product_ids:
        ids = [int(p) for p in product_ids.split(",") if p.strip().isdigit()][:100]
    hour = int(time.time() // 3600)
    result = {}
    for pid in ids:
        best = None
        for rule in RULES:
            if _eligible(pid, rule, hour) and (best is None or rule[3] > best[3]):
                best = rule
        if best:
            result[str(pid)] = {"rule": best[0], "percent_off": best[3], "label": best[4]}
    return {"promotions": result, "evaluated_rules": len(RULES) * len(ids)}
