from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Header, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx

from .config import (
    SERVICE_NAME, CATALOG_SERVICE_URL, CART_SERVICE_URL,
    INVENTORY_SERVICE_URL, PAYMENT_SERVICE_URL, HTTP_TIMEOUT
)
from .database import get_db, init_db, engine
from .models import Order, OrderItem
from .schemas import CheckoutRequest, OrderOut, OrderItemOut
from .metrics import setup_metrics, ORDERS_CREATED_TOTAL

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="Order Management Service", version="1.0.0", lifespan=lifespan)

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

def build_order_out(order: Order) -> OrderOut:
    items_out = [
        OrderItemOut(
            id=item.id,
            product_id=item.product_id,
            quantity=item.quantity,
            unit_price=float(item.unit_price),
            subtotal=round(float(item.unit_price) * item.quantity, 2)
        )
        for item in order.items
    ]
    return OrderOut(
        id=order.id,
        user_id=order.user_id,
        total_amount=float(order.total_amount),
        status=order.status,
        shipping_address=order.shipping_address,
        payment_id=order.payment_id,
        failure_reason=order.failure_reason,
        created_at=order.created_at,
        updated_at=order.updated_at,
        items=items_out
    )

@app.post("/api/orders/checkout", response_model=OrderOut)
async def checkout(
    payload: CheckoutRequest,
    x_idempotency_key: Optional[str] = Header(None),
    db: Session = Depends(get_db)
):
    idempotency_key = payload.idempotency_key or x_idempotency_key
    if idempotency_key:
        existing = db.query(Order).filter(Order.idempotency_key == idempotency_key).first()
        if existing and existing.status == "confirmed":
            return build_order_out(existing)

    items_to_order = []
    # Step 1: If items are passed explicitly, use them; otherwise pull from cart-service
    if payload.items and len(payload.items) > 0:
        items_to_order = [{"product_id": it.product_id, "quantity": it.quantity} for it in payload.items]
    else:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                cart_resp = await client.get(f"{CART_SERVICE_URL}/api/cart/{payload.user_id}")
                if cart_resp.status_code == 200:
                    cart_data = cart_resp.json()
                    for item in cart_data.get("items", []):
                        items_to_order.append({"product_id": item["product_id"], "quantity": item["quantity"]})
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed to communicate with Cart Service: {str(e)}"
            )

    if not items_to_order:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No items to checkout (cart is empty)")

    # Step 2: Validate items & authoritative prices with catalog-service
    total_amount = 0.0
    order_items_data = []
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        for it in items_to_order:
            try:
                prod_resp = await client.get(f"{CATALOG_SERVICE_URL}/api/products/{it['product_id']}")
                if prod_resp.status_code != 200:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Product #{it['product_id']} not found or unavailable in Catalog"
                    )
                prod = prod_resp.json()
                price = float(prod.get("price", 0.0))
                order_items_data.append({
                    "product_id": it["product_id"],
                    "quantity": it["quantity"],
                    "unit_price": price
                })
                total_amount += price * it["quantity"]
            except httpx.RequestError as e:
                raise HTTPException(
                    status_code=status.HTTP_502_BAD_GATEWAY,
                    detail=f"Failed to communicate with Catalog Service: {str(e)}"
                )

    total_amount = round(total_amount, 2)

    # Step 3: Create Order record in 'pending' status
    order = Order(
        user_id=payload.user_id,
        total_amount=total_amount,
        status="pending",
        idempotency_key=idempotency_key,
        shipping_address=payload.shipping_address
    )
    db.add(order)
    db.commit()
    db.refresh(order)

    # Add OrderItems
    for o_item in order_items_data:
        db_item = OrderItem(
            order_id=order.id,
            product_id=o_item["product_id"],
            quantity=o_item["quantity"],
            unit_price=o_item["unit_price"]
        )
        db.add(db_item)
    db.commit()
    db.refresh(order)

    # Step 4: Reserve Inventory
    reserve_payload = {
        "order_id": order.id,
        "items": [{"product_id": it["product_id"], "quantity": it["quantity"]} for it in order_items_data]
    }
    reservation_successful = False
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            inv_resp = await client.post(f"{INVENTORY_SERVICE_URL}/api/inventory/reserve", json=reserve_payload)
            if inv_resp.status_code == 200 and inv_resp.json().get("success"):
                reservation_successful = True
            else:
                err_detail = inv_resp.json().get("detail", "Inventory reservation failed")
                order.status = "failed"
                order.failure_reason = f"Inventory Error: {err_detail}"
                db.commit()
                ORDERS_CREATED_TOTAL.labels(status="failed").inc()
                raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=order.failure_reason)
    except httpx.RequestError as e:
        order.status = "failed"
        order.failure_reason = f"Inventory Service unreachable: {str(e)}"
        db.commit()
        ORDERS_CREATED_TOTAL.labels(status="failed").inc()
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=order.failure_reason)

    # Step 5: Process Payment
    payment_payload = {
        "order_id": order.id,
        "amount": total_amount,
        "card_number": payload.card_number,
        "payment_method": payload.payment_method or "simulated_card",
        "idempotency_key": idempotency_key,
        "simulate_failure": payload.simulate_failure
    }
    payment_successful = False
    payment_id = None
    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            pay_resp = await client.post(f"{PAYMENT_SERVICE_URL}/api/payments/process", json=payment_payload)
            if pay_resp.status_code == 200:
                pay_data = pay_resp.json()
                payment_successful = True
                payment_id = pay_data.get("transaction_id")
            else:
                err_detail = pay_resp.json().get("detail", "Payment declined")
                order.failure_reason = f"Payment Error: {err_detail}"
    except Exception as e:
        order.failure_reason = f"Payment Service error: {str(e)}"

    # Step 6: Coordinate Confirmation or Compensation Rollback
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        if payment_successful:
            # Confirm reservation
            try:
                await client.post(
                    f"{INVENTORY_SERVICE_URL}/api/inventory/confirm",
                    json={"order_id": order.id}
                )
            except Exception as e:
                print(f"Warning: Failed to confirm inventory for order {order.id}: {e}")

            # Clear user cart
            try:
                await client.delete(f"{CART_SERVICE_URL}/api/cart/{payload.user_id}/items")
            except Exception as e:
                print(f"Warning: Failed to clear cart for user {payload.user_id}: {e}")

            order.status = "confirmed"
            order.payment_id = payment_id
            db.commit()
            db.refresh(order)
            ORDERS_CREATED_TOTAL.labels(status="confirmed").inc()
            return build_order_out(order)

        else:
            # Payment failed -> Compensation: Release Inventory Reservation!
            try:
                await client.post(
                    f"{INVENTORY_SERVICE_URL}/api/inventory/release",
                    json={"order_id": order.id}
                )
            except Exception as e:
                print(f"Critical: Failed to release inventory for failed order {order.id}: {e}")

            order.status = "failed"
            db.commit()
            db.refresh(order)
            ORDERS_CREATED_TOTAL.labels(status="failed").inc()
            raise HTTPException(
                status_code=status.HTTP_402_PAYMENT_REQUIRED,
                detail=f"Checkout failed: {order.failure_reason}"
            )

@app.get("/api/orders/user/{user_id}", response_model=List[OrderOut])
def get_user_orders(user_id: int, db: Session = Depends(get_db)):
    orders = db.query(Order).filter(Order.user_id == user_id).order_by(Order.id.desc()).all()
    return [build_order_out(o) for o in orders]

@app.get("/api/orders/{order_id}", response_model=OrderOut)
def get_order_by_id(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return build_order_out(order)

@app.post("/api/orders/{order_id}/cancel", response_model=OrderOut)
async def cancel_order(order_id: int, db: Session = Depends(get_db)):
    order = db.query(Order).filter(Order.id == order_id).first()
    if not order:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    if order.status == "cancelled":
        return build_order_out(order)

    # If pending or reserved, release inventory
    if order.status in ("pending", "confirmed"):
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
                await client.post(
                    f"{INVENTORY_SERVICE_URL}/api/inventory/release",
                    json={"order_id": order.id}
                )
        except Exception as e:
            print(f"Warning: Inventory release failed for cancelled order {order.id}: {e}")

    order.status = "cancelled"
    db.commit()
    db.refresh(order)
    return build_order_out(order)

@app.get("/api/orders", response_model=List[OrderOut])
def list_orders(skip: int = 0, limit: int = 50, db: Session = Depends(get_db)):
    orders = db.query(Order).order_by(Order.id.desc()).offset(skip).limit(limit).all()
    return [build_order_out(o) for o in orders]
