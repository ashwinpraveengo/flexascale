from contextlib import asynccontextmanager
from typing import List, Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import text, or_

from .config import SERVICE_NAME
from .database import get_db, init_db, engine
from .models import Category, Product
from .schemas import (
    CategoryCreate, CategoryOut,
    ProductCreate, ProductUpdate, ProductOut, ProductListResponse
)
from .metrics import setup_metrics

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        init_db()
    except Exception as e:
        print(f"Warning: DB init failed at startup (may be waiting for migrations): {e}")
    yield

app = FastAPI(title="Product Catalog Service", version="1.0.0", lifespan=lifespan)

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

# Categories
@app.get("/api/categories", response_model=List[CategoryOut])
def list_categories(db: Session = Depends(get_db)):
    return db.query(Category).all()

@app.post("/api/categories", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
def create_category(payload: CategoryCreate, db: Session = Depends(get_db)):
    existing = db.query(Category).filter(
        or_(Category.name == payload.name, Category.slug == payload.slug)
    ).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category name or slug already exists")
    cat = Category(**payload.model_dump())
    db.add(cat)
    db.commit()
    db.refresh(cat)
    return cat

@app.get("/api/categories/{category_id}", response_model=CategoryOut)
def get_category(category_id: int, db: Session = Depends(get_db)):
    cat = db.query(Category).filter(Category.id == category_id).first()
    if not cat:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Category not found")
    return cat

# Products
@app.get("/api/products", response_model=ProductListResponse)
def list_products(
    q: Optional[str] = Query(None, description="Search query"),
    category_id: Optional[int] = Query(None, description="Filter by category"),
    min_price: Optional[float] = Query(None, ge=0),
    max_price: Optional[float] = Query(None, ge=0),
    sort_by: Optional[str] = Query("newest", pattern="^(price_asc|price_desc|name_asc|newest)$"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db)
):
    query = db.query(Product).filter(Product.is_active == True)

    if q:
        query = query.filter(
            or_(
                Product.name.ilike(f"%{q}%"),
                Product.description.ilike(f"%{q}%")
            )
        )
    if category_id:
        query = query.filter(Product.category_id == category_id)
    if min_price is not None:
        query = query.filter(Product.price >= min_price)
    if max_price is not None:
        query = query.filter(Product.price <= max_price)

    # Sorting
    if sort_by == "price_asc":
        query = query.order_by(Product.price.asc())
    elif sort_by == "price_desc":
        query = query.order_by(Product.price.desc())
    elif sort_by == "name_asc":
        query = query.order_by(Product.name.asc())
    else:  # newest
        query = query.order_by(Product.id.desc())

    total = query.count()
    items = query.offset((page - 1) * limit).limit(limit).all()

    return ProductListResponse(
        items=[ProductOut.model_validate(p) for p in items],
        total=total,
        page=page,
        limit=limit
    )

@app.get("/api/products/{product_id}", response_model=ProductOut)
def get_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    return ProductOut.model_validate(product)

@app.post("/api/products", response_model=ProductOut, status_code=status.HTTP_201_CREATED)
def create_product(payload: ProductCreate, db: Session = Depends(get_db)):
    existing = db.query(Product).filter(Product.slug == payload.slug).first()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product slug already exists")
    
    if payload.category_id:
        cat = db.query(Category).filter(Category.id == payload.category_id).first()
        if not cat:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Category does not exist")

    product = Product(**payload.model_dump())
    db.add(product)
    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product)

@app.put("/api/products/{product_id}", response_model=ProductOut)
def update_product(product_id: int, payload: ProductUpdate, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")

    update_data = payload.model_dump(exclude_unset=True)
    if "slug" in update_data and update_data["slug"] != product.slug:
        existing = db.query(Product).filter(Product.slug == update_data["slug"]).first()
        if existing:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Product slug already in use")

    for k, v in update_data.items():
        setattr(product, k, v)

    db.commit()
    db.refresh(product)
    return ProductOut.model_validate(product)

@app.delete("/api/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_product(product_id: int, db: Session = Depends(get_db)):
    product = db.query(Product).filter(Product.id == product_id).first()
    if not product:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Product not found")
    # Soft delete
    product.is_active = False
    db.commit()
    return None
