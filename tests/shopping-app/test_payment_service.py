import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys

from conftest import load_service

payment_mod = load_service("payment-service", "svc_payment")
app = payment_mod.app

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

app.dependency_overrides[payment_mod.get_db] = override_get_db
sys.modules["svc_payment.database"].Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_payment_processing_scenarios():
    # 1. Successful payment
    res = client.post("/api/payments/process", json={
        "order_id": 501,
        "amount": 99.95,
        "card_number": "4000000000000001"
    })
    assert res.status_code == 200
    data = res.json()
    assert data["status"] == "success"
    assert "transaction_id" in data
    txn_id = data["transaction_id"]

    # 2. Payment decline with failure card
    decl_res = client.post("/api/payments/process", json={
        "order_id": 502,
        "amount": 50.00,
        "card_number": "4000000000000002"
    })
    assert decl_res.status_code == 402
    assert "Card declined" in decl_res.json()["detail"]

    # 3. Explicit failure flag
    flag_res = client.post("/api/payments/process", json={
        "order_id": 503,
        "amount": 25.00,
        "simulate_failure": True
    })
    assert flag_res.status_code == 402

    # 4. Idempotency test: repeating same request with idempotency key returns exact same transaction
    idemp_key = "idemp_test_key_123"
    res1 = client.post("/api/payments/process", json={
        "order_id": 504,
        "amount": 150.00,
        "idempotency_key": idemp_key
    })
    assert res1.status_code == 200
    txn_id_1 = res1.json()["transaction_id"]

    res2 = client.post("/api/payments/process", json={
        "order_id": 504,
        "amount": 150.00,
        "idempotency_key": idemp_key
    })
    assert res2.status_code == 200
    assert res2.json()["transaction_id"] == txn_id_1
