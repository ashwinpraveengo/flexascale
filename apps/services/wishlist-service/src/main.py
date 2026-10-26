"""Wishlist Service: saved products per user (PostgreSQL, schema `wishlist`).

Reading a wishlist enriches each entry with live product data from
catalog-service.
"""
import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional
import httpx
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy import Column, DateTime, Integer, UniqueConstraint, text
from sqlalchemy.orm import Session

from .database import Base, engine, get_db, init_db, table_args
from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "wishlist-service")
CATALOG_SERVICE_URL = os.getenv("CATALOG_SERVICE_URL", "http://catalog-service:8002")
HTTP_TIMEOUT = float(os.getenv("HTTP_TIMEOUT", "6.0"))
MAX_ITEMS = 20


class WishlistItem(Base):
    __tablename__ = "items"
    __table_args__ = (UniqueConstraint("user_id", "product_id"), table_args)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, nullable=False, index=True)
    product_id = Column(Integer, nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WishlistAdd(BaseModel):
    product_id: int


client: Optional[httpx.AsyncClient] = None


_initialised = False


def ensure_db() -> None:
    """Create the schema (and seed) once; retried from /readyz if PostgreSQL was not up at start."""
    global _initialised
    if not _initialised:
        init_db()
        _initialised = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    global client
    client = httpx.AsyncClient(timeout=HTTP_TIMEOUT)
    try:
        ensure_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield
    await client.aclose()

app = FastAPI(title="Wishlist Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    try:
        ensure_db()
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "service": SERVICE_NAME, "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database not ready: {str(e)}")


async def _product(pid: int) -> Optional[dict]:
    try:
        r = await client.get(f"{CATALOG_SERVICE_URL}/api/products/{pid}")
        return r.json() if r.status_code == 200 else None
    except httpx.RequestError:
        return None


@app.get("/api/wishlist/{user_id}")
async def get_wishlist(user_id: int, db: Session = Depends(get_db)):
    rows = db.query(WishlistItem).filter(WishlistItem.user_id == user_id).order_by(WishlistItem.id.desc()).limit(MAX_ITEMS).all()
    products = await asyncio.gather(*[_product(r.product_id) for r in rows[:5]])
    items = []
    for i, r in enumerate(rows):
        p = products[i] if i < len(products) else None
        items.append({"product_id": r.product_id, "added_at": r.created_at,
                      "name": p["name"] if p else None, "price": p["price"] if p else None})
    return {"user_id": user_id, "count": len(items), "items": items}


@app.post("/api/wishlist/{user_id}/items", status_code=status.HTTP_201_CREATED)
def add_item(user_id: int, payload: WishlistAdd, db: Session = Depends(get_db)):
    existing = db.query(WishlistItem).filter(WishlistItem.user_id == user_id, WishlistItem.product_id == payload.product_id).first()
    if existing:
        return {"user_id": user_id, "product_id": payload.product_id, "created": False}
    if db.query(WishlistItem).filter(WishlistItem.user_id == user_id).count() >= MAX_ITEMS:
        oldest = db.query(WishlistItem).filter(WishlistItem.user_id == user_id).order_by(WishlistItem.id.asc()).first()
        db.delete(oldest)
    db.add(WishlistItem(user_id=user_id, product_id=payload.product_id))
    db.commit()
    return {"user_id": user_id, "product_id": payload.product_id, "created": True}


@app.delete("/api/wishlist/{user_id}/items/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_item(user_id: int, product_id: int, db: Session = Depends(get_db)):
    db.query(WishlistItem).filter(WishlistItem.user_id == user_id, WishlistItem.product_id == product_id).delete()
    db.commit()
