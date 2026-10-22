import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from conftest import load_service

# Load user service
user_mod = load_service("user-service", "svc_user")
app = user_mod.app

from sqlalchemy.pool import StaticPool

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

app.dependency_overrides[user_mod.get_db] = override_get_db
import sys
sys.modules["svc_user.database"].Base.metadata.create_all(bind=engine)

client = TestClient(app)

def test_user_health_and_metrics():
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res = client.get("/metrics")
    assert res.status_code == 200
    assert "http_requests_total" in res.text

def test_user_register_and_login():
    email = "alice@example.com"
    pwd = "AlicePassword123!"

    # 1. Register
    reg = client.post("/api/users/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Alice Wonderland",
        "address": "123 Rabbit Hole"
    })
    assert reg.status_code == 201
    data = reg.json()
    assert "access_token" in data
    assert data["user"]["email"] == email

    # 2. Duplicate registration fails
    dup = client.post("/api/users/register", json={
        "email": email,
        "password": pwd,
        "full_name": "Alice Duplicate"
    })
    assert dup.status_code == 400

    # 3. Login
    login = client.post("/api/users/login", json={
        "email": email,
        "password": pwd
    })
    assert login.status_code == 200
    token = login.json()["access_token"]

    # 4. Profile
    me = client.get("/api/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["full_name"] == "Alice Wonderland"

    # 5. Bad password
    bad = client.post("/api/users/login", json={
        "email": email,
        "password": "WrongPassword!"
    })
    assert bad.status_code == 401
