"""Recommendation Service: "customers also viewed" for a product.

Fetches the catalogue (catalog-service) and rating summaries (review-service),
then ranks candidates by content similarity weighted by rating.
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

SERVICE_NAME = os.getenv("SERVICE_NAME", "recommendation-service")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")
REVIEW_SERVICE_URL = os.getenv("REVIEW_SERVICE_URL", "http://review-service:8009")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "6.0"))

client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    yield
    await client.aclose()

app = FastAPI(title="Recommendation Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

TOKEN = re.compile(r"[a-z0-9]+")


def _vector(p: dict) -> Counter:
    words = TOKEN.findall(f"{p.get('name', '')} {p.get('description', '')}".lower())
    v = Counter()
    for w in words:  # word unigrams + character trigrams
        v[w] += 1.0
        for i in range(len(w) - 2):
            v["#" + w[i:i + 3]] += 0.3
    if p.get("category_id") is not None:
        v[f"cat:{p['category_id']}"] += 3.0
    return v


def _cosine(a: Counter, b: Counter) -> float:
    dot = sum(a[k] * b.get(k, 0.0) for k in a)
    na = math.sqrt(sum(x * x for x in a.values()))
    nb = math.sqrt(sum(x * x for x in b.values()))
    return dot / (na * nb) if na and nb else 0.0


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.get("/api/recommendations/{product_id}")
async def recommend(product_id: int, limit: int = Query(4, ge=1, le=20)):
    try:
        resp = await client.get(f"{CATALOG_SERVICE_URL}/api/products", params={"limit": 100})
        resp.raise_for_status()
    except httpx.HTTPError as e:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"Catalog unavailable: {e}")
    products = resp.json().get("items", [])
    target = next((p for p in products if p["id"] == product_id), None)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    ratings = {}
    try:
        rr = await client.get(f"{REVIEW_SERVICE_URL}/api/reviews/summary")
        if rr.status_code == 200:
            ratings = {int(k): v for k, v in rr.json().items()}
    except httpx.RequestError:
        pass  # similarity only

    tv = _vector(target)
    scored = []
    for p in products:
        if p["id"] == product_id:
            continue
        r = ratings.get(p["id"], {"average": 3.0, "count": 0})
        boost = 0.8 + 0.1 * r["average"] * min(1.0, r["count"] / 5.0 + 0.5)
        scored.append((_cosine(tv, _vector(p)) * boost, p, r))
    scored.sort(key=lambda x: -x[0])
    return {
        "product_id": product_id,
        "recommendations": [
            {"id": p["id"], "name": p["name"], "price": p["price"], "image_url": p.get("image_url"),
             "rating": r["average"], "score": round(s, 4)}
            for s, p, r in scored[:limit]
        ],
    }
