from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient
import httpx

from conftest import load_service

gw_mod = load_service("api-gateway", "svc_gateway")
app = gw_mod.app

client = TestClient(app)

def test_gateway_health_and_root():
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["status"] == "ok"

    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["status"] == "healthy"

def test_gateway_system_status():
    async def mock_health(*args, **kwargs):
        req = httpx.Request("GET", "http://any:8000/healthz")
        return httpx.Response(200, json={"status": "ok"}, request=req)

    with patch("httpx.AsyncClient.get", new_callable=AsyncMock, side_effect=mock_health):
        res = client.get("/api/system/status")
        assert res.status_code == 200
        data = res.json()
        assert data["gateway"] == "healthy"
        assert data["all_services_healthy"] is True
        assert "users" in data["services"]
        assert "products" in data["services"]
        assert "orders" in data["services"]

def test_gateway_route_forwarding():
    async def mock_forward(*args, **kwargs):
        req = httpx.Request("GET", "http://catalog-service:8002/api/products")
        return httpx.Response(200, json={"items": [{"id": 1, "name": "Test"}], "total": 1}, request=req)

    with patch("httpx.AsyncClient.request", new_callable=AsyncMock, side_effect=mock_forward):
        res = client.get("/api/products")
        assert res.status_code == 200
        assert res.json()["total"] == 1
