"""
Demo control panel for the Sceptic demo site.

Runs on your own PC (not in a container), because it needs the Docker CLI to stop, start, pause, and restart the
demo container. It talks to the demo site over HTTP for fault injection and test traffic.

Start it from the project root:
    .\\venv\\Scripts\\python.exe -m uvicorn demo.control.app:app --port 8091
Then open http://localhost:8091
"""
import os
import subprocess
from pathlib import Path

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

CONTAINER_NAME = os.getenv("DEMO_CONTAINER_NAME", "sceptic-demo-site")
SITE_URL = os.getenv("DEMO_SITE_URL", "http://localhost:8090").rstrip("/")
DOCKER_TIMEOUT_SECONDS = 60

# Only these Docker commands can be run from the panel.
ALLOWED_ACTIONS = {"stop", "start", "restart", "pause", "unpause"}
MAX_TRAFFIC_REQUESTS = 200

INDEX_HTML = Path(__file__).with_name("index.html")

app = FastAPI(title="Sceptic Demo Control Panel")


class FaultRequest(BaseModel):
    error_rate: int = Field(0, ge=0, le=100)
    latency_ms: int = Field(0, ge=0, le=10000)


class TrafficRequest(BaseModel):
    count: int = Field(20, ge=1, le=MAX_TRAFFIC_REQUESTS)


def _container_state() -> str:
    try:
        proc = subprocess.run(
            ["docker", "inspect", "--format", "{{.State.Status}}", CONTAINER_NAME],
            capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "docker unavailable"
    if proc.returncode != 0:
        return "missing"
    return proc.stdout.strip() or "unknown"


def _site_fault() -> dict:
    try:
        with httpx.Client(timeout=3.0) as client:
            return client.get(f"{SITE_URL}/admin/fault").json()
    except (httpx.HTTPError, ValueError):
        return {}


@app.get("/")
def index():
    return FileResponse(INDEX_HTML)


@app.get("/api/status")
def status():
    site_reachable = False
    try:
        with httpx.Client(timeout=3.0) as client:
            site_reachable = client.get(f"{SITE_URL}/health").status_code == 200
    except httpx.HTTPError:
        pass
    return {
        "container": CONTAINER_NAME,
        "container_state": _container_state(),
        "site_reachable": site_reachable,
        "fault": _site_fault(),
    }


@app.post("/api/container/{action}")
def container_action(action: str):
    if action not in ALLOWED_ACTIONS:
        raise HTTPException(status_code=400, detail=f"Action must be one of: {', '.join(sorted(ALLOWED_ACTIONS))}")
    try:
        proc = subprocess.run(
            ["docker", action, CONTAINER_NAME],
            capture_output=True, text=True, timeout=DOCKER_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired) as e:
        raise HTTPException(status_code=500, detail=f"Could not run docker {action}: {e}")
    if proc.returncode != 0:
        raise HTTPException(status_code=500, detail=(proc.stderr or proc.stdout).strip() or f"docker {action} failed")
    return {"action": action, "container": CONTAINER_NAME, "state": _container_state()}


@app.post("/api/fault")
def set_fault(req: FaultRequest):
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.post(f"{SITE_URL}/admin/fault", json=req.model_dump())
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Demo site is not reachable: {e}")
    if resp.status_code != 200:
        raise HTTPException(status_code=resp.status_code, detail=resp.text)
    return resp.json()


@app.post("/api/traffic")
def send_traffic(req: TrafficRequest):
    ok = failed = 0
    try:
        with httpx.Client(timeout=10.0) as client:
            for i in range(req.count):
                path = "/api/orders" if i % 3 else "/api/checkout"
                method = client.get if path == "/api/orders" else client.post
                try:
                    resp = method(f"{SITE_URL}{path}")
                    if resp.status_code < 400:
                        ok += 1
                    else:
                        failed += 1
                except httpx.HTTPError:
                    failed += 1
    except httpx.HTTPError as e:
        raise HTTPException(status_code=503, detail=f"Demo site is not reachable: {e}")
    return {"sent": req.count, "ok": ok, "failed": failed}
