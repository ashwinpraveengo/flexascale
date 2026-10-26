"""Notification Service: renders and "sends" order confirmation messages.

Leaf service. Called by order-service after a confirmed checkout; the call is
best effort (a failure never fails the order). Messages are kept in a small
in-memory ring buffer per pod for inspection; nothing is actually sent.
"""
import collections
import hashlib
import os
import time
from typing import List
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from .metrics import setup_metrics

SERVICE_NAME = os.getenv("SERVICE_NAME", "notification-service")

app = FastAPI(title="Notification Service", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

RECENT = collections.deque(maxlen=200)

TEMPLATE = """Hello customer #{user_id},

Thank you for your order #{order_id}. We have received your payment of {amount:.2f}.

{lines}

Track your parcel with reference {ref}.
-- FlexaScale Shop
"""


class NotifyItem(BaseModel):
    product_id: int
    quantity: int = 1


class OrderNotification(BaseModel):
    order_id: int
    user_id: int
    amount: float
    items: List[NotifyItem] = []


@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}


@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}


@app.post("/api/notifications/order")
def notify_order(n: OrderNotification):
    lines = "\n".join(f"  - product {it.product_id} x {it.quantity}" for it in n.items) or "  (no items)"
    ref = hashlib.sha256(f"{n.order_id}:{n.user_id}".encode()).hexdigest()[:12].upper()
    body = TEMPLATE.format(user_id=n.user_id, order_id=n.order_id, amount=n.amount, lines=lines, ref=ref)
    # Sign the message (stands in for templating, i18n and DKIM signing work).
    sig = body.encode()
    for _ in range(300):
        sig = hashlib.sha256(sig).digest()
    RECENT.append({"order_id": n.order_id, "user_id": n.user_id, "ref": ref, "ts": time.time()})
    return {"queued": True, "channel": "email", "reference": ref, "signature": sig.hex()[:16]}


@app.get("/api/notifications/recent")
def recent():
    return list(RECENT)[-20:]
