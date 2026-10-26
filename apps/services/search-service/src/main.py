"""Search Service: ranked full-text product search with live prices.

Fetches the active catalogue from catalog-service, ranks it with BM25 over
name and description, then prices the top results through pricing-service
(which in turn calls promotion-service): gateway -> search -> pricing -> promotion.
"""
import math
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from typing import Optional
import httpx
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "search-service")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")
PRICING_SERVICE_URL = os.getenv("PRICING_SERVICE_URL", "http://pricing-service:8010")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "6.0"))

client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    yield
    await client.aclose()

app = FastAPI(title="Search Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

TOKEN = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list:
    out = []
    for t in TOKEN.findall((text or "").lower()):
        out.append(t)
        out += [t[:n] for n in range(3, len(t))]  # prefixes, so "head" matches "headphones"
    return out


def bm25_rank(products: list, query: str, k1: float = 1.4, b: float = 0.75) -> list:
    docs = [_tokens(f"{p.get('name', '')} {p.get('name', '')} {p.get('description', '')}") for p in products]
    if not docs:
        return []
    avgdl = sum(len(d) for d in docs) / len(docs) or 1.0
    df = Counter(t for d in docs for t in set(d))
    q = _tokens(query)
    scored = []
    for p, d in zip(products, docs):
        tf = Counter(d)
        s = 0.0
        for t in q:
            if t not in tf:
                continue
            idf = math.log(1 + (len(docs) - df[t] + 0.5) / (df[t] + 0.5))
            s += idf * tf[t] * (k1 + 1) / (tf[t] + k1 * (1 - b + b * len(d) / avgdl))
        if s > 0:
            scored.append((s, p))
    scored.sort(key=lambda x: -x[0])
    return scored


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/api/search")
async def search(q: str = Query(..., min_length=1), limit: int = Query(10, ge=1, le=50)):
    try:
        resp = await client.get(f"{CATALOG_SERVICE_URL}/api/products", params={"limit": 100})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Catalog unavailable: {e}")
    products = resp.json().get("items", [])
    ranked = bm25_rank(products, q)[:limit]

    prices = {}
    if ranked:
        items = [{"product_id": p["id"], "unit_price": p["price"], "quantity": 1} for _, p in ranked]
        try:
            pr = await client.post(f"{PRICING_SERVICE_URL}/api/pricing/quote", json={"items": items})
            if pr.status_code == 200:
                prices = {line["product_id"]: line for line in pr.json().get("lines", [])}
        except httpx.RequestError:
            pass  # list prices only

    results = []
    for score, p in ranked:
        line = prices.get(p["id"])
        results.append({
            "id": p["id"], "name": p["name"], "slug": p.get("slug"), "image_url": p.get("image_url"),
            "price": p["price"], "final_price": round(p["price"] - line["discount"], 2) if line else p["price"],
            "promotion": line["promotion"] if line else None, "score": round(score, 3),
        })
    return {"query": q, "total": len(results), "results": results}
