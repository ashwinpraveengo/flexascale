import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
import sys

from conftest import load_service

inventory_mod = load_service("inventory-service", "svc_inventory")
app = inventory_mod.app

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

app.dependency_overrides[inventory_mod.get_db] = override_get_db
sys.modules["svc_inventory.database"].Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_inventory_stock_and_atomic_reservation():
    prod_id = 42

    # 1. Set initial stock to 10
    set_res = client.put(f"/api/inventory/{prod_id}", json={"stock_quantity": 10})
    assert set_res.status_code == 200
    assert set_res.json()["stock_quantity"] == 10
    assert set_res.json()["available_quantity"] == 10

    # 2. Adjust stock (+5)
    adj = client.post(f"/api/inventory/{prod_id}/adjust", json={"adjustment": 5})
    assert adj.json()["stock_quantity"] == 15
    assert adj.json()["available_quantity"] == 15

    # 3. Reserve 4 items
    res_resp = client.post("/api/inventory/reserve", json={
        "order_id": 1001,
        "items": [{"product_id": prod_id, "quantity": 4}]
    })
    assert res_resp.status_code == 200
    res_data = res_resp.json()
    assert res_data["success"] is True
    res_id = res_data["reservations"][0]["reservation_id"]

    # Verify available stock is now 15 - 4 = 11
    chk = client.get(f"/api/inventory/{prod_id}").json()
    assert chk["stock_quantity"] == 15
    assert chk["reserved_quantity"] == 4
    assert chk["available_quantity"] == 11

    # 4. Attempt to reserve more than available (requesting 12 when only 11 available) -> Must fail!
    fail_res = client.post("/api/inventory/reserve", json={
        "order_id": 1002,
        "items": [{"product_id": prod_id, "quantity": 12}]
    })
    assert fail_res.status_code == 400

    # 5. Release reservation (simulating payment failure compensation)
    rel_res = client.post("/api/inventory/release", json={"order_id": 1001})
    assert rel_res.status_code == 200
    assert rel_res.json()["released_count"] == 1

    # Verify stock restored to available
    chk2 = client.get(f"/api/inventory/{prod_id}").json()
    assert chk2["reserved_quantity"] == 0
    assert chk2["available_quantity"] == 15

    # 6. Re-reserve and Confirm
    client.post("/api/inventory/reserve", json={
        "order_id": 1003,
        "items": [{"product_id": prod_id, "quantity": 5}]
    })
    conf_res = client.post("/api/inventory/confirm", json={"order_id": 1003})
    assert conf_res.status_code == 200
    assert conf_res.json()["confirmed_count"] == 1

    # Verify permanent stock deduction (15 - 5 = 10)
    chk3 = client.get(f"/api/inventory/{prod_id}").json()
    assert chk3["stock_quantity"] == 10
    assert chk3["reserved_quantity"] == 0
    assert chk3["available_quantity"] == 10
