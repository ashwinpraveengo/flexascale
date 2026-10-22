import time
from typing import Callable
from fastapi import Request, Response
from prometheus_client import CollectorRegistry, Counter, Histogram, Gauge, generate_latest, CONTENT_TYPE_LATEST

registry = CollectorRegistry()

REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests handled",
    ["service", "method", "endpoint", "status"],
    registry=registry
)

REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "Histogram of HTTP request latencies in seconds",
    ["service", "method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
    registry=registry
)

REQUESTS_IN_FLIGHT = Gauge(
    "http_requests_in_flight",
    "Current number of in-flight requests",
    ["service", "method", "endpoint"],
    registry=registry
)

INVENTORY_RESERVATIONS_TOTAL = Counter(
    "inventory_reservations_total",
    "Total inventory reservation attempts",
    ["status"],
    registry=registry
)

def get_normalized_path(request: Request) -> str:
    for route in request.app.routes:
        match, _ = route.matches(request.scope)
        if match.value == 2:
            return getattr(route, "path", request.url.path)
    return request.url.path

def setup_metrics(app, service_name: str):
    @app.middleware("http")
    async def metrics_middleware(request: Request, call_next: Callable):
        if request.url.path in ("/metrics", "/healthz", "/readyz"):
            return await call_next(request)

        endpoint = get_normalized_path(request)
        method = request.method

        REQUESTS_IN_FLIGHT.labels(service=service_name, method=method, endpoint=endpoint).inc()
        start_time = time.perf_counter()
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception:
            raise
        finally:
            duration = time.perf_counter() - start_time
            REQUESTS_IN_FLIGHT.labels(service=service_name, method=method, endpoint=endpoint).dec()
            REQUESTS_TOTAL.labels(
                service=service_name,
                method=method,
                endpoint=endpoint,
                status=str(status_code)
            ).inc()
            REQUEST_DURATION_SECONDS.labels(
                service=service_name,
                method=method,
                endpoint=endpoint
            ).observe(duration)

    @app.get("/metrics", include_in_schema=False)
    def metrics():
        return Response(content=generate_latest(registry), media_type=CONTENT_TYPE_LATEST)
