"""Shipping Service: quotes delivery options for an order.

Leaf service. Called by order-service during checkout (required step).
"""
import hashlib
import math
import os
from typing import List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "shipping-service")

app = FastAPI(title="Shipping Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

WAREHOUSES = [(12.97, 77.59), (19.07, 72.87), (28.61, 77.20), (13.08, 80.27), (22.57, 88.36)]
CARRIERS = [("standard", 4.99, 5), ("express", 12.99, 2), ("same_day", 24.99, 0)]


class ShipItem(BaseModel):
    product_id: int
    quantity: int = Field(1, ge=1)


class QuoteRequest(BaseModel):
    shipping_address: str = ""
    items: List[ShipItem] = []


def _address_coords(address: str) -> tuple:
    # Deterministic "geocoding" of the free-text address.
    h = hashlib.sha256(address.encode() or b"-").digest()
    for _ in range(60):
        h = hashlib.sha256(h).digest()
    return 8.0 + h[0] / 255 * 26.0, 68.0 + h[1] / 255 * 29.0


def _haversine_km(a: tuple, b: tuple) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    d = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 2 * 6371 * math.asin(math.sqrt(d))


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/api/shipping/quote")
def quote(payload: QuoteRequest):
    dest = _address_coords(payload.shipping_address)
    distance, warehouse = min((_haversine_km(w, dest), i) for i, w in enumerate(WAREHOUSES))
    units = sum(it.quantity for it in payload.items) or 1
    weight_kg = sum(0.4 + (it.product_id % 7) * 0.3 for it in payload.items for _ in range(it.quantity)) or 0.5
    options = []
    for name, base, days in CARRIERS:
        cost = base + 0.002 * distance * math.log1p(weight_kg) + 0.5 * (units - 1)
        options.append({"carrier": name, "cost": round(cost, 2), "eta_days": days + int(distance // 900)})
    return {"warehouse": warehouse, "distance_km": round(distance, 1), "weight_kg": round(weight_kg, 2), "options": options}
