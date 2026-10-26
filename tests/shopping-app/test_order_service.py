from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys
import httpx

from conftest import load_service

order_mod = load_service("order-service", "svc_order")
app = order_mod.app

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

app.dependency_overrides[order_mod.get_db] = override_get_db
sys.modules["svc_order.database"].Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_order_checkout_saga_success():
    """Validates complete successful 2-phase checkout saga."""
    def mock_get(url, *args, **kwargs):
        req = httpx.Request("GET", str(url))
        if "products/1" in str(url):
            return httpx.Response(200, json={"id": 1, "name": "Mechanical Keyboard", "price": 150.00}, request=req)
        return httpx.Response(200, json={}, request=req)

    def mock_post(url, *args, **kwargs):
        req = httpx.Request("POST", str(url))
        if "fraud/check" in str(url):
            return httpx.Response(200, json={"score": 0.01, "approved": True}, request=req)
        if "inventory/reserve" in str(url):
            return httpx.Response(200, json={"success": True, "reservations": [{"reservation_id": "res_123"}]}, request=req)
        elif "payments/process" in str(url):
            return httpx.Response(200, json={"status": "success", "transaction_id": "txn_abc123"}, request=req)
        elif "inventory/confirm" in str(url):
            return httpx.Response(200, json={"status": "confirmed"}, request=req)
        return httpx.Response(200, json={}, request=req)

    def mock_delete(url, *args, **kwargs):
        req = httpx.Request("DELETE", str(url))
        return httpx.Response(204, request=req)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post), \
         patch("httpx.AsyncClient.delete", new_callable=AsyncMock, side_effect=mock_delete):

        resp = client.post("/api/orders/checkout", json={
            "user_id": 10,
            "items": [{"product_id": 1, "quantity": 2}],
            "shipping_address": "456 Microservice Lane",
            "card_number": "4000000000000001",
            "idempotency_key": "idemp_order_saga_1"
        })

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "confirmed"
        assert float(data["total_amount"]) == 300.00
        assert data["payment_id"] == "txn_abc123"

def test_order_checkout_saga_payment_failure_rollback():
    """Validates that when payment fails, the inventory reservation is released via compensation!"""
    released_called = False

    def mock_get(url, *args, **kwargs):
        req = httpx.Request("GET", str(url))
        if "products/1" in str(url):
            return httpx.Response(200, json={"id": 1, "name": "Mechanical Keyboard", "price": 150.00}, request=req)
        return httpx.Response(200, json={}, request=req)

    def mock_post(url, *args, **kwargs):
        nonlocal released_called
        req = httpx.Request("POST", str(url))
        if "fraud/check" in str(url):
            return httpx.Response(200, json={"score": 0.01, "approved": True}, request=req)
        if "inventory/reserve" in str(url):
            return httpx.Response(200, json={"success": True, "reservations": [{"reservation_id": "res_999"}]}, request=req)
        elif "payments/process" in str(url):
            # Payment decline!
            return httpx.Response(402, json={"detail": "Card declined"}, request=req)
        elif "inventory/release" in str(url):
            released_called = True
            return httpx.Response(200, json={"status": "released"}, request=req)
        return httpx.Response(200, json={}, request=req)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):

        resp = client.post("/api/orders/checkout", json={
            "user_id": 11,
            "items": [{"product_id": 1, "quantity": 1}],
            "shipping_address": "456 Microservice Lane",
            "card_number": "4000000000000002"
        })

        assert resp.status_code == 402
        assert released_called is True


def test_order_checkout_rejected_by_fraud_screening():
    """A fraud rejection stops the saga before any inventory is reserved."""
    calls = []

    def mock_get(url, *args, **kwargs):
        req = httpx.Request("GET", str(url))
        return httpx.Response(200, json={"id": 1, "name": "Mechanical Keyboard", "price": 150.00}, request=req)

    def mock_post(url, *args, **kwargs):
        calls.append(str(url))
        req = httpx.Request("POST", str(url))
        if "fraud/check" in str(url):
            return httpx.Response(200, json={"score": 0.99, "approved": False}, request=req)
        return httpx.Response(200, json={}, request=req)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_get), \
         patch("httpx.AsyncClient.post", new_callable=AsyncMock, side_effect=mock_post):
        resp = client.post("/api/orders/checkout", json={
            "user_id": 11,
            "items": [{"product_id": 1, "quantity": 1}],
            "shipping_address": "1 Fraud Street",
            "card_number": "4000000000000001",
            "idempotency_key": "idemp_order_fraud_1"
        })

    assert resp.status_code == 403
    assert not any("inventory/reserve" in c for c in calls)



def test_user_order_history_is_bounded():
    """Order history returns only the newest orders (unbounded loads OOM-killed the pod)."""
    Order = sys.modules["svc_order.models"].Order
    db = TestingSession()
    db.add_all([Order(user_id=77, total_amount=1.0, status="confirmed") for _ in range(30)])
    db.commit()
    newest = db.query(Order.id).filter(Order.user_id == 77).order_by(Order.id.desc()).first()[0]
    db.close()

    res = client.get("/api/orders/user/77")
    assert res.status_code == 200
    assert len(res.json()) == 20 and res.json()[0]["id"] == newest
    assert len(client.get("/api/orders/user/77?limit=5").json()) == 5
    assert client.get("/api/orders/user/77?limit=1000").status_code == 422
