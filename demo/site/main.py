"""
Sceptic Demo Site.

A small business-style API that Prometheus scrapes and Grafana charts.
The control panel in demo/control/ can inject errors and latency here, and can stop or pause the container.
Local demo only: the /admin/fault endpoint has no authentication.
"""
import asyncio
import random
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from prometheus_client import Counter, Gauge, Histogram, CONTENT_TYPE_LATEST, REGISTRY, generate_latest
from fastapi import Response

app = FastAPI(title="Sceptic Demo Site", version="1.0.0")

# Same metric names as the target service, so the Sceptic dashboards work on this site too.
HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by the demo site",
    ["method", "endpoint", "status_code"],
)
HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of active HTTP requests currently in progress",
    ["method", "endpoint"],
)

# Current fault settings. Changed through /admin/fault, applied to /api/* routes only.
FAULT = {"error_rate": 0, "latency_ms": 0}

ORDERS = [
    {"id": 1, "item": "Keyboard", "total": 49.0},
    {"id": 2, "item": "Monitor", "total": 219.0},
    {"id": 3, "item": "USB hub", "total": 19.5},
]


@app.middleware("http")
async def observe_and_inject_faults(request: Request, call_next):
    endpoint = request.url.path
    method = request.method
    HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
    start = time.perf_counter()
    status_code = 500
    try:
        if endpoint.startswith("/api/"):
            if FAULT["latency_ms"] > 0:
                await asyncio.sleep(FAULT["latency_ms"] / 1000)
            if FAULT["error_rate"] > 0 and random.randint(1, 100) <= FAULT["error_rate"]:
                response = JSONResponse({"detail": "Injected failure"}, status_code=500)
            else:
                response = await call_next(request)
        else:
            response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(time.perf_counter() - start)
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()


class FaultSettings(BaseModel):
    error_rate: int = Field(0, ge=0, le=100, description="Percent of /api/* requests that fail with 500")
    latency_ms: int = Field(0, ge=0, le=10000, description="Extra delay added to /api/* requests")


INDEX_HTML = Path(__file__).with_name("index.html")


@app.get("/")
def storefront():
    return FileResponse(INDEX_HTML)


@app.get("/health")
def health():
    return {"status": "healthy"}


@app.get("/version")
def version():
    return {"service": "demo-site", "version": "1.0.0", "environment": "demo"}


@app.get("/api/orders")
def list_orders():
    return {"orders": ORDERS, "time": datetime.now(timezone.utc).isoformat()}


@app.post("/api/checkout", status_code=201)
def checkout():
    order = {"id": len(ORDERS) + 1, "item": "Demo item", "total": round(random.uniform(5, 300), 2)}
    ORDERS.append(order)
    return order


@app.get("/admin/fault")
def get_fault():
    return FAULT


@app.post("/admin/fault")
def set_fault(settings: FaultSettings):
    FAULT["error_rate"] = settings.error_rate
    FAULT["latency_ms"] = settings.latency_ms
    return FAULT


@app.get("/metrics")
def metrics():
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)
