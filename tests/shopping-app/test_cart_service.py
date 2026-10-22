from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys
import httpx

from conftest import load_service

cart_mod = load_service("cart-service", "svc_cart")
app = cart_mod.app

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

app.dependency_overrides[cart_mod.get_db] = override_get_db
sys.modules["svc_cart.database"].Base.metadata.create_all(bind=engine)

client = TestClient(app)

@pytest.mark.anyio
async def test_cart_operations():
    user_id = 101

    mock_resp = httpx.Response(200, json={
        "id": 1,
        "name": "Wireless Headphones",
        "price": 99.50,
        "image_url": "https://example.com/img.jpg"
    }, request=httpx.Request("GET", "http://catalog-service:8002/api/products/1"))

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, return_value=mock_resp):
        # 1. Add item to cart
        add_res = client.post(f"/api/cart/{user_id}/items", json={
            "product_id": 1,
            "quantity": 2
        })
        assert add_res.status_code == 200
        data = add_res.json()
        assert data["total_items"] == 2
        assert float(data["total_amount"]) == 199.00
        item_id = data["items"][0]["id"]

        # 2. Update item quantity
        upd_res = client.put(f"/api/cart/{user_id}/items/{item_id}", json={
            "quantity": 3
        })
        assert upd_res.status_code == 200
        assert upd_res.json()["total_items"] == 3
        assert float(upd_res.json()["total_amount"]) == 298.50

        # 3. Clear cart
        del_res = client.delete(f"/api/cart/{user_id}/items")
        assert del_res.status_code == 204

        cart_empty = client.get(f"/api/cart/{user_id}").json()
        assert len(cart_empty["items"]) == 0
        assert cart_empty["total_amount"] == 0.0
