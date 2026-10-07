"""
Sceptic Target Service.
Independent deployable microservice exposing runtime health, versioning, and demo endpoints.
Designed for post-deployment monitoring, drift detection, and rollback verification.
"""
import os
from datetime import datetime, timezone
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(
    title="Sceptic Target Service",
    description="Deployable target service monitored by Sceptic verification agents",
    version=os.getenv("APPLICATION_VERSION", "1.0.0")
)


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
            "/api/demo"
        ]
    }
