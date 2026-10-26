from contextlib import asynccontextmanager
import asyncio
from typing import Dict, Any, Optional
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
import httpx

from .config import (
    SERVICE_NAME, HTTP_TIMEOUT,
    USER_SERVICE_URL, CATALOG_SERVICE_URL, CART_SERVICE_URL,
    ORDER_SERVICE_URL, INVENTORY_SERVICE_URL, PAYMENT_SERVICE_URL,
    SEARCH_SERVICE_URL, RECOMMENDATION_SERVICE_URL, REVIEW_SERVICE_URL,
    PRICING_SERVICE_URL, SHIPPING_SERVICE_URL, WISHLIST_SERVICE_URL
)
from .metrics import setup_metrics, GATEWAY_FORWARD_TOTAL


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
    "search": SEARCH_SERVICE_URL,
    "recommendations": RECOMMENDATION_SERVICE_URL,
    "reviews": REVIEW_SERVICE_URL,
    "pricing": PRICING_SERVICE_URL,
    "shipping": SHIPPING_SERVICE_URL,
    "wishlist": WISHLIST_SERVICE_URL,
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
    async with shared_client() as client:
        for name, url in SERVICE_MAP.items():
            if name in ("categories",):  # Handled by catalog-service
                continue
            try:
                resp = await client.get(f"{url}/healthz", timeout=3.0)
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
        async with shared_client() as client:
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

@app.api_route("/api/search", methods=["GET"])
async def route_search(request: Request):
    return await forward_request(SEARCH_SERVICE_URL, request, "/api/search")

@app.api_route("/api/recommendations/{path:path}", methods=["GET"])
async def route_recommendations(path: str, request: Request):
    return await forward_request(RECOMMENDATION_SERVICE_URL, request, f"/api/recommendations/{path}")

@app.api_route("/api/reviews/{path:path}", methods=["GET", "POST"])
async def route_reviews(path: str, request: Request):
    return await forward_request(REVIEW_SERVICE_URL, request, f"/api/reviews/{path}")

@app.api_route("/api/pricing/{path:path}", methods=["POST"])
async def route_pricing(path: str, request: Request):
    return await forward_request(PRICING_SERVICE_URL, request, f"/api/pricing/{path}")

@app.api_route("/api/shipping/{path:path}", methods=["POST"])
async def route_shipping(path: str, request: Request):
    return await forward_request(SHIPPING_SERVICE_URL, request, f"/api/shipping/{path}")

@app.api_route("/api/wishlist/{path:path}", methods=["GET", "POST", "DELETE"])
async def route_wishlist(path: str, request: Request):
    return await forward_request(WISHLIST_SERVICE_URL, request, f"/api/wishlist/{path}")
