from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import uuid
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text

from .config import SERVICE_NAME, RESERVATION_EXPIRY_MINUTES
from .database import get_db, init_db, engine
from .models import InventoryItem, Reservation
from .schemas import (
    InventoryOut, StockUpdateRequest, StockAdjustRequest,
    ReserveRequest, ReserveResponse, ReservationItemOut,
    ConfirmReleaseRequest
)
from .metrics import setup_metrics, INVENTORY_RESERVATIONS_TOTAL

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="Inventory Service", version="1.0.0", lifespan=lifespan)

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

def get_or_create_inventory(product_id: int, db: Session, for_update: bool = False) -> InventoryItem:
    query = db.query(InventoryItem).filter(InventoryItem.product_id == product_id)
    if for_update:
        query = query.with_for_update()
    item = query.first()
    if not item:
        item = InventoryItem(product_id=product_id, stock_quantity=0, reserved_quantity=0)
        db.add(item)
        db.flush()
    return item

@app.get("/api/inventory/{product_id}", response_model=InventoryOut)
def get_inventory(product_id: int, db: Session = Depends(get_db)):
    item = get_or_create_inventory(product_id, db)
    return InventoryOut(
        product_id=item.product_id,
        stock_quantity=item.stock_quantity,
        reserved_quantity=item.reserved_quantity,
        available_quantity=max(0, item.stock_quantity - item.reserved_quantity),
        updated_at=item.updated_at
    )

@app.get("/api/inventory", response_model=List[InventoryOut])
def list_inventory(skip: int = 0, limit: int = 100, db: Session = Depends(get_db)):
    items = db.query(InventoryItem).offset(skip).limit(limit).all()
    return [
        InventoryOut(
            product_id=i.product_id,
            stock_quantity=i.stock_quantity,
            reserved_quantity=i.reserved_quantity,
            available_quantity=max(0, i.stock_quantity - i.reserved_quantity),
            updated_at=i.updated_at
        )
        for i in items
    ]

@app.put("/api/inventory/{product_id}", response_model=InventoryOut)
def set_stock(product_id: int, payload: StockUpdateRequest, db: Session = Depends(get_db)):
    item = get_or_create_inventory(product_id, db, for_update=True)
    item.stock_quantity = payload.stock_quantity
    db.commit()
    db.refresh(item)
    return InventoryOut(
        product_id=item.product_id,
        stock_quantity=item.stock_quantity,
        reserved_quantity=item.reserved_quantity,
        available_quantity=max(0, item.stock_quantity - item.reserved_quantity),
        updated_at=item.updated_at
    )

@app.post("/api/inventory/{product_id}/adjust", response_model=InventoryOut)
def adjust_stock(product_id: int, payload: StockAdjustRequest, db: Session = Depends(get_db)):
    item = get_or_create_inventory(product_id, db, for_update=True)
    new_stock = item.stock_quantity + payload.adjustment
    if new_stock < 0:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Stock cannot be negative")
    item.stock_quantity = new_stock
    db.commit()
    db.refresh(item)
    return InventoryOut(
        product_id=item.product_id,
        stock_quantity=item.stock_quantity,
        reserved_quantity=item.reserved_quantity,
        available_quantity=max(0, item.stock_quantity - item.reserved_quantity),
        updated_at=item.updated_at
    )

@app.post("/api/inventory/reserve", response_model=ReserveResponse)
def reserve_inventory(payload: ReserveRequest, db: Session = Depends(get_db)):
    if not payload.items:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="No items to reserve")

    # Sort items by product_id to prevent database deadlocks
    sorted_items = sorted(payload.items, key=lambda x: x.product_id)

    reservations_out = []
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=RESERVATION_EXPIRY_MINUTES)

    try:
        # Phase 1: Check availability and lock rows
        for item_req in sorted_items:
            inv = get_or_create_inventory(item_req.product_id, db, for_update=True)
            available = inv.stock_quantity - inv.reserved_quantity
            if available < item_req.quantity:
                INVENTORY_RESERVATIONS_TOTAL.labels(status="insufficient_stock").inc()
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Insufficient inventory for product {item_req.product_id}. Available: {available}, Requested: {item_req.quantity}"
                )

        # Phase 2: Reserve
        for item_req in sorted_items:
            inv = get_or_create_inventory(item_req.product_id, db)
            inv.reserved_quantity += item_req.quantity

            res_id = f"res_{uuid.uuid4().hex[:16]}"
            res = Reservation(
                id=res_id,
                order_id=payload.order_id,
                product_id=item_req.product_id,
                quantity=item_req.quantity,
                status="reserved",
                expires_at=expires_at
            )
            db.add(res)
            reservations_out.append(ReservationItemOut(
                reservation_id=res_id,
                product_id=item_req.product_id,
                quantity=item_req.quantity,
                status="reserved"
            ))

        db.commit()
        INVENTORY_RESERVATIONS_TOTAL.labels(status="success").inc()
        return ReserveResponse(success=True, reservations=reservations_out)

    except HTTPException:
        db.rollback()
        raise
    except Exception as e:
        db.rollback()
        INVENTORY_RESERVATIONS_TOTAL.labels(status="error").inc()
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"Reservation failed: {str(e)}")

@app.post("/api/inventory/confirm")
def confirm_reservation(payload: ConfirmReleaseRequest, db: Session = Depends(get_db)):
    query = db.query(Reservation).filter(Reservation.status == "reserved")
    if payload.order_id:
        query = query.filter(Reservation.order_id == payload.order_id)
    elif payload.reservation_ids:
        query = query.filter(Reservation.id.in_(payload.reservation_ids))
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must provide order_id or reservation_ids")

    reservations = query.all()
    if not reservations:
        return {"status": "no_active_reservations_found", "confirmed_count": 0}

    for res in reservations:
        inv = get_or_create_inventory(res.product_id, db, for_update=True)
        inv.stock_quantity = max(0, inv.stock_quantity - res.quantity)
        inv.reserved_quantity = max(0, inv.reserved_quantity - res.quantity)
        res.status = "confirmed"

    db.commit()
    return {"status": "confirmed", "confirmed_count": len(reservations)}

@app.post("/api/inventory/release")
def release_reservation(payload: ConfirmReleaseRequest, db: Session = Depends(get_db)):
    query = db.query(Reservation).filter(Reservation.status == "reserved")
    if payload.order_id:
        query = query.filter(Reservation.order_id == payload.order_id)
    elif payload.reservation_ids:
        query = query.filter(Reservation.id.in_(payload.reservation_ids))
    else:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Must provide order_id or reservation_ids")

    reservations = query.all()
    if not reservations:
        return {"status": "no_active_reservations_found", "released_count": 0}

    for res in reservations:
        inv = get_or_create_inventory(res.product_id, db, for_update=True)
        inv.reserved_quantity = max(0, inv.reserved_quantity - res.quantity)
        res.status = "released"

    db.commit()
    return {"status": "released", "released_count": len(reservations)}
