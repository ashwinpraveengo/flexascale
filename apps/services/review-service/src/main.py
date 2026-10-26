"""Review Service: product reviews and rating summaries (PostgreSQL, schema `review`).

Read by the product page (via the gateway) and by recommendation-service.
Seeds a deterministic set of reviews on first start so ratings exist.
"""
import os
import random
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import List
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy import Column, DateTime, Integer, String, Text, func, text
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine, get_db, init_db, table_args
from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "review-service")
SEED_PRODUCTS = int(os.getenv("REVIEW_SEED_PRODUCTS", "14"))


class Review(Base):
    __tablename__ = "reviews"
    __table_args__ = table_args

    id = Column(Integer, primary_key=True, index=True)
    product_id = Column(Integer, nullable=False, index=True)
    user_id = Column(Integer, nullable=False)
    rating = Column(Integer, nullable=False)
    title = Column(String(120), nullable=False)
    body = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class ReviewIn(BaseModel):
    user_id: int
    rating: int = Field(..., ge=1, le=5)
    title: str = Field(..., min_length=1, max_length=120)
    body: str = ""


TITLES = ["Great value", "Works as described", "Could be better", "Excellent quality", "Not for me", "Would buy again"]


def seed():
    db = SessionLocal()
    try:
        if db.query(Review).count() > 0:
            return
        rng = random.Random(42)
        for pid in range(1, SEED_PRODUCTS + 1):
            for _ in range(rng.randint(2, 6)):
                r = rng.choice([3, 4, 4, 5, 5, 2])
                db.add(Review(product_id=pid, user_id=rng.randint(2, 3), rating=r, title=rng.choice(TITLES), body=""))
        db.commit()
    finally:
        db.close()


_initialised = False


def ensure_db() -> None:
    """Create the schema (and seed) once; retried from /readyz if PostgreSQL was not up at start."""
    global _initialised
    if not _initialised:
        init_db()
        seed()
        _initialised = True


@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        ensure_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="Review Service", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)


def _out(r: Review) -> dict:
    return {"id": r.id, "product_id": r.product_id, "user_id": r.user_id, "rating": r.rating,
            "title": r.title, "body": r.body, "created_at": r.created_at}


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


@app.get("/api/reviews/summary")
def summary(db: Session = Depends(get_db)):
    rows = db.query(Review.product_id, func.avg(Review.rating), func.count(Review.id)).group_by(Review.product_id).all()
    return {str(pid): {"average": round(float(avg), 2), "count": int(n)} for pid, avg, n in rows}


@app.get("/api/reviews/{product_id}")
def list_reviews(product_id: int, limit: int = Query(10, ge=1, le=50), db: Session = Depends(get_db)):
    q = db.query(Review).filter(Review.product_id == product_id)
    reviews: List[Review] = q.order_by(Review.id.desc()).limit(limit).all()
    agg = db.query(func.avg(Review.rating), func.count(Review.id)).filter(Review.product_id == product_id).one()
    return {
        "product_id": product_id,
        "average": round(float(agg[0]), 2) if agg[0] is not None else None,
        "count": int(agg[1]),
        "reviews": [_out(r) for r in reviews],
    }


@app.post("/api/reviews/{product_id}", status_code=status.HTTP_201_CREATED)
def add_review(product_id: int, payload: ReviewIn, db: Session = Depends(get_db)):
    r = Review(product_id=product_id, **payload.model_dump())
    db.add(r)
    db.commit()
    db.refresh(r)
    return _out(r)
