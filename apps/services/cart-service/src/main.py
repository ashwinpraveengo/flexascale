from contextlib import asynccontextmanager
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text
import httpx

from .config import SERVICE_NAME, CATALOG_SERVICE_URL, INVENTORY_SERVICE_URL, PRICING_SERVICE_URL, HTTP_TIMEOUT
from .database import get_db, init_db, engine
from .models import Cart, CartItem
from .schemas import CartItemAdd, CartItemUpdate, CartItemOut, CartOut
from .metrics import setup_metrics


_http_client: Optional[httpx.AsyncClient] = None


@asynccontextmanager
async def shared_client():
    """One pooled HTTP client per process. A client per call (the earlier code) built a new
    connection pool and TLS context every time; under checkout bursts that pushed the pod
    past its memory limit (OOMKilled)."""
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(
            timeout=HTTP_TIMEOUT, limits=httpx.Limits(max_connections=200, max_keepalive_connections=50))
    yield _http_client

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="Shopping Cart Service", version="1.0.0", lifespan=lifespan)

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

def get_or_create_cart(user_id: int, db: Session) -> Cart:
    cart = db.query(Cart).filter(Cart.user_id == user_id).first()
    if not cart:
        cart = Cart(user_id=user_id)
        db.add(cart)
        db.commit()
        db.refresh(cart)
    return cart

async def fetch_product_details(product_id: int) -> Optional[dict]:
    try:
        async with shared_client() as client:
            resp = await client.get(f"{CATALOG_SERVICE_URL}/api/products/{product_id}")
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        print(f"Error fetching product {product_id} from catalog service: {e}")
    return None

async def check_inventory_availability(product_id: int, quantity: int) -> bool:
    try:
        async with shared_client() as client:
            resp = await client.get(f"{INVENTORY_SERVICE_URL}/api/inventory/{product_id}")
            if resp.status_code == 200:
                data = resp.json()
                available = data.get("stock_quantity", 0) - data.get("reserved_quantity", 0)
                return available >= quantity
    except Exception as e:
        print(f"Warning: Could not check inventory for product {product_id}: {e}")
    return True

async def fetch_price_quote(items: list):
    """Promotions and tax from pricing-service; best effort (None = list prices only)."""
    if not items:
        return None
    try:
        async with shared_client() as client:
            resp = await client.post(f"{PRICING_SERVICE_URL}/api/pricing/quote", json={"items": [
                {"product_id": it.product_id, "unit_price": it.unit_price, "quantity": it.quantity} for it in items
            ]})
            if resp.status_code == 200:
                return resp.json()
    except Exception as e:
        print(f"Warning: pricing quote failed: {e}")
    return None

@app.get("/api/cart/{user_id}", response_model=CartOut)
async def get_cart(user_id: int, db: Session = Depends(get_db)):
    cart = get_or_create_cart(user_id, db)
    
    items_out = []
    total_amount = 0.0
    total_items = 0

    for item in cart.items:
        prod_data = await fetch_product_details(item.product_id)
        name = prod_data.get("name") if prod_data else f"Product #{item.product_id}"
        price = float(prod_data.get("price", 0.0)) if prod_data else 0.0
        img = prod_data.get("image_url") if prod_data else None
        subtotal = round(price * item.quantity, 2)
        total_amount += subtotal
        total_items += item.quantity

        items_out.append(CartItemOut(
            id=item.id,
            product_id=item.product_id,
            quantity=item.quantity,
            product_name=name,
            unit_price=price,
            subtotal=subtotal,
            image_url=img,
            in_stock=True
        ))

    quote = await fetch_price_quote(items_out)

    return CartOut(
        id=cart.id,
        user_id=cart.user_id,
        items=items_out,
        total_items=total_items,
        total_amount=round(total_amount, 2),
        discount=quote["discount"] if quote else 0.0,
        tax=quote["tax"] if quote else None,
        payable_total=quote["total"] if quote else None,
        updated_at=cart.updated_at
    )

@app.post("/api/cart/{user_id}/items", response_model=CartOut)
async def add_item_to_cart(user_id: int, payload: CartItemAdd, db: Session = Depends(get_db)):
    # Validate product exists in catalog
    prod = await fetch_product_details(payload.product_id)
    if not prod:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found in catalog")

    cart = get_or_create_cart(user_id, db)
    
    item = db.query(CartItem).filter(
        CartItem.cart_id == cart.id,
        CartItem.product_id == payload.product_id
    ).first()

    if item:
        item.quantity += payload.quantity
    else:
        item = CartItem(
            cart_id=cart.id,
            product_id=payload.product_id,
            quantity=payload.quantity
        )
        db.add(item)

    db.commit()
    return await get_cart(user_id, db)

@app.put("/api/cart/{user_id}/items/{item_id}", response_model=CartOut)
async def update_cart_item(user_id: int, item_id: int, payload: CartItemUpdate, db: Session = Depends(get_db)):
    cart = get_or_create_cart(user_id, db)
    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")

    item.quantity = payload.quantity
    db.commit()
    return await get_cart(user_id, db)

@app.delete("/api/cart/{user_id}/items/{item_id}", response_model=CartOut)
async def remove_cart_item(user_id: int, item_id: int, db: Session = Depends(get_db)):
    cart = get_or_create_cart(user_id, db)
    item = db.query(CartItem).filter(CartItem.id == item_id, CartItem.cart_id == cart.id).first()
    if not item:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cart item not found")

    db.delete(item)
    db.commit()
    return await get_cart(user_id, db)

@app.delete("/api/cart/{user_id}/items", status_code=status.HTTP_204_NO_CONTENT)
def clear_cart(user_id: int, db: Session = Depends(get_db)):
    cart = db.query(Cart).filter(Cart.user_id == user_id).first()
    if cart:
        db.query(CartItem).filter(CartItem.cart_id == cart.id).delete()
        db.commit()
    return None
