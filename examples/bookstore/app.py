"""
Generic synthetic microservice for the FlexaScale portability test ("bookstore").

One image, five roles. Behaviour comes from environment variables:
    SERVICE_NAME  name used in metrics labels
    WORK_MS       CPU-bound work per request (busy loop), milliseconds
    ROUTES        "op=svcA,svcB;op2=svcC": downstream services called for /api/<op>
                  (each downstream is called at http://<svc>:8080/api/default)
    DOWNSTREAM    downstream services for /api/default

Exposes the common Prometheus conventions http_requests_total and
http_request_duration_seconds. Contains no FlexaScale-specific code.
"""

import json
import os
import time
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

NAME = os.getenv("SERVICE_NAME", "svc")
WORK_MS = float(os.getenv("WORK_MS", "5"))
PORT = int(os.getenv("PORT", "8080"))


def _parse_routes(spec: str) -> dict:
    routes = {}
    for part in filter(None, spec.split(";")):
        op, _, svcs = part.partition("=")
        routes[op.strip()] = [s.strip() for s in svcs.split(",") if s.strip()]
    return routes


ROUTES = _parse_routes(os.getenv("ROUTES", ""))
ROUTES.setdefault("default", [s for s in os.getenv("DOWNSTREAM", "").split(",") if s])

REQS = Counter("http_requests_total", "HTTP requests", ["service", "method", "endpoint", "status"])
LAT = Histogram(
    "http_request_duration_seconds", "HTTP request latency", ["service", "method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)


def burn(ms: float) -> None:
    end = time.perf_counter() + ms / 1000.0
    x = 0
    while time.perf_counter() < end:
        x += 1


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *args):  # quiet
        pass

    def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/metrics":
            return self._send(200, generate_latest(), CONTENT_TYPE_LATEST)
        if path in ("/healthz", "/readyz"):
            return self._send(200, b'{"status":"ok"}')
        op = path.strip("/").split("/")[-1] if path.startswith("/api/") else ("home" if path == "/" else "")
        if op not in ROUTES:
            return self._send(404, b'{"error":"unknown operation"}')
        start = time.perf_counter()
        status = 200
        calls = []
        try:
            burn(WORK_MS)
            for svc in ROUTES[op]:
                with urllib.request.urlopen(f"http://{svc}:8080/api/default", timeout=10) as resp:
                    calls.append({"service": svc, "status": resp.status})
            body = json.dumps({"service": NAME, "op": op, "downstream": calls}).encode()
        except Exception as exc:
            status = 502
            body = json.dumps({"service": NAME, "op": op, "error": str(exc)}).encode()
        LAT.labels(NAME, "GET", f"/api/{op}").observe(time.perf_counter() - start)
        REQS.labels(NAME, "GET", f"/api/{op}", str(status)).inc()
        self._send(status, body)


if __name__ == "__main__":
    print(f"{NAME} listening on :{PORT} work={WORK_MS}ms routes={ROUTES}", flush=True)
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
