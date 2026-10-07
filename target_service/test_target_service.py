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
