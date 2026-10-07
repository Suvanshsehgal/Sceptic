import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from fastapi.testclient import TestClient
from target_service.main import app

client = TestClient(app)


def test_target_health_endpoint():
    response = client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"


def test_target_version_endpoint_defaults():
    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert "version" in data
    assert "commit_sha" in data
    assert "build_timestamp" in data
    assert "environment" in data


def test_target_version_environment_overrides(monkeypatch):
    monkeypatch.setenv("APPLICATION_VERSION", "2.4.0-rc1")
    monkeypatch.setenv("COMMIT_SHA", "abcdef1234567890")
    monkeypatch.setenv("BUILD_TIMESTAMP", "2026-10-07T12:00:00Z")
    monkeypatch.setenv("ENVIRONMENT", "staging")

    response = client.get("/version")
    assert response.status_code == 200
    data = response.json()
    assert data["version"] == "2.4.0-rc1"
    assert data["commit_sha"] == "abcdef1234567890"
    assert data["build_timestamp"] == "2026-10-07T12:00:00Z"
    assert data["environment"] == "staging"


def test_target_demo_endpoint():
    response = client.get("/api/demo")
    assert response.status_code == 200
    data = response.json()
    assert data["service"] == "target-service"
    assert data["status"] == "operational"
    assert "/health" in data["endpoints"]
    assert "/version" in data["endpoints"]
    assert "/api/demo" in data["endpoints"]
    assert "/metrics" in data["endpoints"]


def test_target_metrics_endpoint_and_real_activity():
    """Verify /metrics exposes Prometheus format and increments counters with real traffic."""
    # Hit endpoints to generate activity
    h_resp = client.get("/health")
    assert h_resp.status_code == 200

    v_resp = client.get("/version")
    assert v_resp.status_code == 200

    d_resp = client.get("/api/demo")
    assert d_resp.status_code == 200

    # Scrape /metrics
    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text

    # Verify standard metrics and labels
    assert "http_requests_total" in metrics_text
    assert 'endpoint="/health"' in metrics_text
    assert 'endpoint="/version"' in metrics_text
    assert 'endpoint="/api/demo"' in metrics_text
    assert 'status_code="200"' in metrics_text
    assert "http_request_duration_seconds" in metrics_text
    assert "target_service_app_info" in metrics_text
    assert "http_requests_in_progress" in metrics_text


def test_target_metrics_app_info_and_safety():
    """Verify app_info contains deployment metadata and does not leak secrets."""
    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text

    # Verify expected non-sensitive deployment metadata labels
    assert "target_service_app_info{" in metrics_text
    assert "version=" in metrics_text
    assert "commit_sha=" in metrics_text
    assert "environment=" in metrics_text

    # Verify absence of sensitive tokens or connection strings
    assert "password" not in metrics_text.lower()
    assert "secret" not in metrics_text.lower()
    assert "database_url" not in metrics_text.lower()
    assert "bearer" not in metrics_text.lower()


def test_simulated_failure_metrics():
    """Verify failure endpoint records 500 status code and increments error counts."""
    fail_resp = client.get("/api/fail?code=500")
    assert fail_resp.status_code == 500

    metrics_resp = client.get("/metrics")
    assert metrics_resp.status_code == 200
    metrics_text = metrics_resp.text

    # Ensure 500 status code is recorded in http_requests_total
    assert 'status_code="500"' in metrics_text
    assert 'endpoint="/api/fail"' in metrics_text

