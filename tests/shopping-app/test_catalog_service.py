import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys

from conftest import load_service

catalog_mod = load_service("catalog-service", "svc_catalog")
app = catalog_mod.app

engine = create_engine(
    "sqlite:///:memory:",
    connect_args={"check_same_thread": False},
    poolclass=StaticPool
)
TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def override_get_db():
    db = TestingSession()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[catalog_mod.get_db] = override_get_db
sys.modules["svc_catalog.database"].Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_catalog_health():
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

def test_catalog_category_and_product_crud():
    # 1. Create Category
    cat_resp = client.post("/api/categories", json={
        "name": "Audio",
        "slug": "audio",
        "description": "Headphones and Speakers"
    })
    assert cat_resp.status_code == 201
    cat_id = cat_resp.json()["id"]

    # 2. List Categories
    cats = client.get("/api/categories").json()
    assert len(cats) >= 1
    assert cats[0]["slug"] == "audio"

    # 3. Create Product
    prod_resp = client.post("/api/products", json={
        "name": "Noise Cancelling Headphones",
        "slug": "noise-cancelling-headphones",
        "description": "Studio quality wireless headphones",
        "price": 199.99,
        "category_id": cat_id,
        "image_url": "https://example.com/headphones.jpg"
    })
    assert prod_resp.status_code == 201
    prod = prod_resp.json()
    assert prod["name"] == "Noise Cancelling Headphones"
    prod_id = prod["id"]

    # 4. Search and Filter Products
    res = client.get("/api/products?q=headphones")
    assert res.status_code == 200
    items = res.json()["items"]
    assert len(items) == 1
    assert items[0]["id"] == prod_id

    # 5. Filter by price
    res_price = client.get("/api/products?min_price=250")
    assert len(res_price.json()["items"]) == 0

    res_price2 = client.get("/api/products?min_price=100&max_price=200")
    assert len(res_price2.json()["items"]) == 1

    # 6. Update Product
    upd = client.put(f"/api/products/{prod_id}", json={
        "price": 179.99
    })
    assert upd.status_code == 200
    assert float(upd.json()["price"]) == 179.99

    # 7. Delete Product (Soft delete)
    del_res = client.delete(f"/api/products/{prod_id}")
    assert del_res.status_code == 204

    # Deleted product is no longer in active listing
    active = client.get("/api/products").json()["items"]
    assert len(active) == 0
