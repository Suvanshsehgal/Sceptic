"""
Sceptic Target Service.
Independent deployable microservice exposing runtime health, versioning, demo endpoints,
and Prometheus-compatible runtime metrics.
Designed for post-deployment monitoring, drift detection, and rollback verification.
"""
import os
import time
from datetime import datetime, timezone
from fastapi import FastAPI, Request, Response, HTTPException, status
from pydantic import BaseModel
from prometheus_client import (
    Counter,
    Histogram,
    Gauge,
    generate_latest,
    CONTENT_TYPE_LATEST,
    REGISTRY
)

app = FastAPI(
    title="Sceptic Target Service",
    description="Deployable target service monitored by Sceptic verification agents",
    version=os.getenv("APPLICATION_VERSION", "1.0.0")
)

# ========================================================
# PROMETHEUS METRICS DEFINITIONS
# ========================================================

HTTP_REQUESTS_TOTAL = Counter(
    "http_requests_total",
    "Total count of HTTP requests processed by the target service",
    ["method", "endpoint", "status_code"]
)

HTTP_REQUEST_DURATION_SECONDS = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
)

HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "http_requests_in_progress",
    "Number of active HTTP requests currently in progress",
    ["method", "endpoint"]
)

APP_INFO = Gauge(
    "target_service_app_info",
    "Application release metadata and deployment identity",
    ["version", "commit_sha", "build_timestamp", "environment"]
)

def update_app_info_metric():
    version = os.getenv("APPLICATION_VERSION", "1.0.0")
    commit_sha = os.getenv("COMMIT_SHA", "dev-initial")
    build_timestamp = os.getenv("BUILD_TIMESTAMP", "2026-10-07T00:00:00Z")
    environment = os.getenv("ENVIRONMENT", "development")
    APP_INFO.labels(
        version=version,
        commit_sha=commit_sha,
        build_timestamp=build_timestamp,
        environment=environment
    ).set(1)

update_app_info_metric()


# ========================================================
# METRICS MIDDLEWARE
# ========================================================

@app.middleware("http")
async def prometheus_metrics_middleware(request: Request, call_next):
    endpoint = request.url.path
    method = request.method

    HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).inc()
    start_time = time.perf_counter()
    status_code = 500

    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    except Exception:
        status_code = 500
        raise
    finally:
        latency = time.perf_counter() - start_time
        HTTP_REQUESTS_IN_PROGRESS.labels(method=method, endpoint=endpoint).dec()
        HTTP_REQUEST_DURATION_SECONDS.labels(method=method, endpoint=endpoint).observe(latency)
        HTTP_REQUESTS_TOTAL.labels(method=method, endpoint=endpoint, status_code=str(status_code)).inc()


# ========================================================
# MODELS & ENDPOINTS
# ========================================================

class HealthResponse(BaseModel):
    status: str


class VersionResponse(BaseModel):
    version: str
    commit_sha: str
    build_timestamp: str
    environment: str


class DemoResponse(BaseModel):
    service: str
    status: str
    message: str
    endpoints: list[str]


@app.get("/metrics")
def get_metrics():
    """
    Exposes Prometheus-compatible metrics for scraping.
    """
    update_app_info_metric()
    return Response(content=generate_latest(REGISTRY), media_type=CONTENT_TYPE_LATEST)


@app.get("/health", response_model=HealthResponse)
def get_health():
    """
    Machine-readable health status endpoint for Docker health checks
    and Pipeline Watchdog monitoring.
    """
    return {"status": "healthy"}


@app.get("/version", response_model=VersionResponse)
def get_version():
    """
    Exposes runtime deployment metadata for Gatekeeper and Rollback verification.
    Does not expose sensitive environment secrets.
    """
    return {
        "version": os.getenv("APPLICATION_VERSION", "1.0.0"),
        "commit_sha": os.getenv("COMMIT_SHA", "dev-initial"),
        "build_timestamp": os.getenv("BUILD_TIMESTAMP", "2026-10-07T00:00:00Z"),
        "environment": os.getenv("ENVIRONMENT", "development")
    }


@app.get("/api/demo", response_model=DemoResponse)
def get_demo():
    """
    Demonstration API endpoint verifying service responsiveness.
    """
    return {
        "service": "target-service",
        "status": "operational",
        "message": "Target application is running and ready for verification",
        "endpoints": [
            "/health",
            "/version",
            "/api/demo",
            "/metrics",
            "/api/fail"
        ]
    }


@app.get("/api/fail")
def trigger_simulated_failure(code: int = 500):
    """
    Diagnostic endpoint to simulate an application failure for observability testing.
    """
    raise HTTPException(status_code=code, detail=f"Simulated application error with status {code}")

