import asyncio
from contextlib import asynccontextmanager
import random
from typing import List, Optional
import uuid
from fastapi import FastAPI, Depends, HTTPException, Header, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import SERVICE_NAME, SIMULATE_FAILURE_RATE, PAYMENT_DEFAULT_DELAY_MS
from .database import get_db, init_db, engine
from .models import Payment
from .schemas import PaymentProcessRequest, PaymentProcessResponse, PaymentOut
from .metrics import setup_metrics, PAYMENTS_PROCESSED_TOTAL

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="Payment Service (Simulated)", version="1.0.0", lifespan=lifespan)

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
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return {"status": "ready", "service": SERVICE_NAME, "database": "connected"}
    except Exception as e:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=f"Database not ready: {str(e)}")

@app.post("/api/payments/process", response_model=PaymentProcessResponse)
async def process_payment(
    payload: PaymentProcessRequest,
    x_payment_delay_ms: Optional[int] = Header(None),
    x_idempotency_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    # Determine idempotency key
    idempotency_key = payload.idempotency_key or x_idempotency_key

    # Check for idempotent request
    if idempotency_key:
        existing = db.query(Payment).filter(Payment.idempotency_key == idempotency_key).first()
        if existing:
            return PaymentProcessResponse(
                transaction_id=existing.transaction_id,
                order_id=existing.order_id,
                amount=float(existing.amount),
                status=existing.status,
                payment_method=existing.payment_method,
                failure_message=existing.failure_message,
                created_at=existing.created_at
            )

    # Configurable latency simulation for load testing
    delay_ms = payload.delay_ms if payload.delay_ms is not None else x_payment_delay_ms
    if delay_ms is None:
        delay_ms = PAYMENT_DEFAULT_DELAY_MS
    if delay_ms > 0:
        await asyncio.sleep(delay_ms / 1000.0)

    # Determine success or failure
    is_failed = False
    failure_reason = None

    if payload.simulate_failure:
        is_failed = True
        failure_reason = "Simulated payment failure (explicit flag)"
    elif payload.card_number and (
        "fail" in payload.card_number.lower() or
        payload.card_number.endswith("0002") or
        payload.card_number.endswith("9999")
    ):
        is_failed = True
        failure_reason = "Card declined: insufficient funds or invalid card number"
    elif SIMULATE_FAILURE_RATE > 0.0 and random.random() < SIMULATE_FAILURE_RATE:
        is_failed = True
        failure_reason = "Simulated bank gateway timeout/error"

    txn_status = "failed" if is_failed else "success"
    transaction_id = f"txn_{uuid.uuid4().hex[:16]}"

    payment = Payment(
        transaction_id=transaction_id,
        order_id=payload.order_id,
        amount=payload.amount,
        status=txn_status,
        payment_method=payload.payment_method or "simulated_card",
        idempotency_key=idempotency_key,
        failure_message=failure_reason
    )
    db.add(payment)
    db.commit()
    db.refresh(payment)

    PAYMENTS_PROCESSED_TOTAL.labels(status=txn_status).inc()

    if is_failed:
        raise HTTPException(
            status_code=status.HTTP_402_PAYMENT_REQUIRED,
            detail=f"Payment failed: {failure_reason}"
        )

    return PaymentProcessResponse(
        transaction_id=payment.transaction_id,
        order_id=payment.order_id,
        amount=float(payment.amount),
        status=payment.status,
        payment_method=payment.payment_method,
        failure_message=payment.failure_message,
        created_at=payment.created_at
    )

@app.get("/api/payments/order/{order_id}", response_model=List[PaymentOut])
def get_payments_by_order(order_id: int, db: Session = Depends(get_db)):
    payments = db.query(Payment).filter(Payment.order_id == order_id).all()
    return [PaymentOut.model_validate(p) for p in payments]

@app.get("/api/payments/{transaction_id}", response_model=PaymentOut)
def get_payment_by_txn(transaction_id: str, db: Session = Depends(get_db)):
    payment = db.query(Payment).filter(Payment.transaction_id == transaction_id).first()
    if not payment:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Payment transaction not found")
    return PaymentOut.model_validate(payment)
