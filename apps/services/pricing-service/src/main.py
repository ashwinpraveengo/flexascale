"""Pricing Service: computes final prices (promotions, tax) for a list of items.

Calls promotion-service for the active promotions. Used by search-service
(result prices), cart-service (cart totals) and order-service (checkout).
"""
import os
from contextlib import asynccontextmanager
from typing import List, Optional
import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "pricing-service")
PROMOTION_SERVICE_URL = os.getenv("PROMOTION_SERVICE_URL", "http://promotion-service:8011")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "6.0"))
TAX_RATE = float(os.getenv("PRICING_TAX_RATE", "0.18"))

client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    yield
    await client.aclose()

app = FastAPI(title="Pricing Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)


class PriceItem(BaseModel):
    product_id: int
    unit_price: float = Field(..., ge=0)
    quantity: int = Field(1, ge=1)


class QuoteRequest(BaseModel):
    items: List[PriceItem]
    user_id: Optional[int] = None


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/api/pricing/quote")
async def quote(payload: QuoteRequest):
    promotions = {}
    degraded = False
    if payload.items:
        ids = ",".join(str(it.product_id) for it in payload.items[:100])
        try:
            resp = await client.get(f"{PROMOTION_SERVICE_URL}/api/promotions/active", params={"product_ids": ids})
            if resp.status_code == 200:
                promotions = resp.json().get("promotions", {})
            else:
                degraded = True
        except httpx.RequestError:
            degraded = True  # price without promotions rather than fail the caller

    lines, subtotal, discount = [], 0.0, 0.0
    for it in payload.items:
        gross = it.unit_price * it.quantity
        promo = promotions.get(str(it.product_id))
        off = round(gross * promo["percent_off"] / 100.0, 2) if promo else 0.0
        subtotal += gross
        discount += off
        lines.append({
            "product_id": it.product_id, "quantity": it.quantity, "unit_price": it.unit_price,
            "gross": round(gross, 2), "discount": off, "promotion": promo["rule"] if promo else None,
        })
    taxable = subtotal - discount
    tax = round(taxable * TAX_RATE, 2)
    return {
        "lines": lines, "subtotal": round(subtotal, 2), "discount": round(discount, 2),
        "tax": tax, "total": round(taxable + tax, 2), "promotions_degraded": degraded,
    }
