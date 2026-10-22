import asyncio
from typing import Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import httpx

from .config import (
    SERVICE_NAME, HTTP_TIMEOUT,
    USER_SERVICE_URL, CATALOG_SERVICE_URL, CART_SERVICE_URL,
    ORDER_SERVICE_URL, INVENTORY_SERVICE_URL, PAYMENT_SERVICE_URL
)
from .metrics import setup_metrics, GATEWAY_FORWARD_TOTAL

app = FastAPI(title="API Gateway", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

setup_metrics(app, SERVICE_NAME)

SERVICE_MAP = {
    "users": USER_SERVICE_URL,
    "products": CATALOG_SERVICE_URL,
    "categories": CATALOG_SERVICE_URL,
    "cart": CART_SERVICE_URL,
    "orders": ORDER_SERVICE_URL,
    "inventory": INVENTORY_SERVICE_URL,
    "payments": PAYMENT_SERVICE_URL,
}

@app.get("/")
def read_root():
    return {
        "service": SERVICE_NAME,
        "status": "healthy",
        "description": "FlexaScale E-Commerce Microservices Gateway"
    }

@app.get("/healthz", tags=["Health"])
def health_check():
    return {"status": "ok", "service": SERVICE_NAME}

@app.get("/readyz", tags=["Health"])
def ready_check():
    return {"status": "ready", "service": SERVICE_NAME}

@app.get("/api/system/status", tags=["System"])
async def system_status():
    """Checks the health and responsiveness of all registered downstream microservices."""
    results: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=3.0) as client:
        for name, url in SERVICE_MAP.items():
            if name in ("categories",):  # Handled by catalog-service
                continue
            try:
                resp = await client.get(f"{url}/healthz")
                results[name] = {
                    "url": url,
                    "status": "up" if resp.status_code == 200 else "degraded",
                    "status_code": resp.status_code
                }
            except Exception as e:
                results[name] = {
                    "url": url,
                    "status": "down",
                    "error": str(e)
                }

    all_up = all(v["status"] == "up" for v in results.values())
    return {
        "gateway": "healthy",
        "all_services_healthy": all_up,
        "services": results
    }

async def forward_request(target_base_url: str, request: Request, path: str) -> Response:
    url = f"{target_base_url}{path}"
    if request.url.query:
        url = f"{url}?{request.url.query}"

    headers = dict(request.headers)
    # Exclude hop-by-hop headers
    headers.pop("host", None)
    headers.pop("content-length", None)

    body = await request.body()
    method = request.method

    try:
        async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
            resp = await client.request(
                method=method,
                url=url,
                headers=headers,
                content=body
            )

            # Filter response headers
            resp_headers = dict(resp.headers)
            resp_headers.pop("content-length", None)
            resp_headers.pop("content-encoding", None)
            resp_headers.pop("transfer-encoding", None)

            GATEWAY_FORWARD_TOTAL.labels(
                target_service=target_base_url.split("//")[-1].split(":")[0],
                status=str(resp.status_code)
            ).inc()

            return Response(
                content=resp.content,
                status_code=resp.status_code,
                headers=resp_headers,
                media_type=resp.headers.get("content-type")
            )

    except httpx.TimeoutException:
        GATEWAY_FORWARD_TOTAL.labels(
            target_service=target_base_url.split("//")[-1].split(":")[0],
            status="504"
        ).inc()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail=f"Timeout communicating with downstream service at {target_base_url}"
        )
    except Exception as e:
        GATEWAY_FORWARD_TOTAL.labels(
            target_service=target_base_url.split("//")[-1].split(":")[0],
            status="502"
        ).inc()
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Downstream service unavailable ({target_base_url}): {str(e)}"
        )

# Route definitions
@app.api_route("/api/users/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def route_users(path: str, request: Request):
    return await forward_request(USER_SERVICE_URL, request, f"/api/users/{path}")

@app.api_route("/api/users", methods=["GET", "POST"])
async def route_users_root(request: Request):
    return await forward_request(USER_SERVICE_URL, request, "/api/users")

@app.api_route("/api/products/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_products(path: str, request: Request):
    return await forward_request(CATALOG_SERVICE_URL, request, f"/api/products/{path}")

@app.api_route("/api/products", methods=["GET", "POST"])
async def route_products_root(request: Request):
    return await forward_request(CATALOG_SERVICE_URL, request, "/api/products")

@app.api_route("/api/categories/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_categories(path: str, request: Request):
    return await forward_request(CATALOG_SERVICE_URL, request, f"/api/categories/{path}")

@app.api_route("/api/categories", methods=["GET", "POST"])
async def route_categories_root(request: Request):
    return await forward_request(CATALOG_SERVICE_URL, request, "/api/categories")

@app.api_route("/api/cart/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_cart(path: str, request: Request):
    return await forward_request(CART_SERVICE_URL, request, f"/api/cart/{path}")

@app.api_route("/api/orders/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_orders(path: str, request: Request):
    return await forward_request(ORDER_SERVICE_URL, request, f"/api/orders/{path}")

@app.api_route("/api/orders", methods=["GET", "POST"])
async def route_orders_root(request: Request):
    return await forward_request(ORDER_SERVICE_URL, request, "/api/orders")

@app.api_route("/api/inventory/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_inventory(path: str, request: Request):
    return await forward_request(INVENTORY_SERVICE_URL, request, f"/api/inventory/{path}")

@app.api_route("/api/inventory", methods=["GET", "POST"])
async def route_inventory_root(request: Request):
    return await forward_request(INVENTORY_SERVICE_URL, request, "/api/inventory")

@app.api_route("/api/payments/{path:path}", methods=["GET", "POST", "PUT", "DELETE"])
async def route_payments(path: str, request: Request):
    return await forward_request(PAYMENT_SERVICE_URL, request, f"/api/payments/{path}")

@app.api_route("/api/payments", methods=["GET", "POST"])
async def route_payments_root(request: Request):
    return await forward_request(PAYMENT_SERVICE_URL, request, "/api/payments")
