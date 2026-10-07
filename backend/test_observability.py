import json
import os
import sys
import yaml
import pytest

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

from fastapi.testclient import TestClient
from target_service.main import app




def test_prometheus_configuration_validity():
    """Verify Prometheus scrape configuration exists and properly targets target-service:8080/metrics."""
    prom_path = os.path.join(REPO_ROOT, "infra", "prometheus", "prometheus.yml")
    assert os.path.exists(prom_path), f"Missing Prometheus config at {prom_path}"

    with open(prom_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    assert "scrape_configs" in config
    jobs = {j["job_name"]: j for j in config["scrape_configs"]}

    assert "target-service" in jobs, "target-service job missing in prometheus.yml"
    target_job = jobs["target-service"]
    assert target_job.get("metrics_path") == "/metrics"

    targets = [
        target
        for sc in target_job.get("static_configs", [])
        for target in sc.get("targets", [])
    ]
    assert any("target-service:8080" in t for t in targets), "target-service:8080 must be a scrape target"


def test_grafana_datasource_provisioning():
    """Verify Grafana datasource provisioning config exists and points to Prometheus."""
    ds_path = os.path.join(REPO_ROOT, "infra", "grafana", "provisioning", "datasources", "prometheus.yml")
    assert os.path.exists(ds_path), f"Missing Grafana datasource config at {ds_path}"

    with open(ds_path, "r", encoding="utf-8") as f:
        ds_config = yaml.safe_load(f)

    assert "datasources" in ds_config
    datasources = ds_config["datasources"]
    assert len(datasources) >= 1

    prom_ds = next((ds for ds in datasources if ds.get("type") == "prometheus"), None)
    assert prom_ds is not None, "Prometheus datasource missing"
    assert prom_ds.get("url") == "http://prometheus:9090", "Prometheus datasource must use internal container URL"


def test_grafana_dashboard_provisioning():
    """Verify Grafana dashboard provider provisioning config exists and points to dashboard directory."""
    provider_path = os.path.join(REPO_ROOT, "infra", "grafana", "provisioning", "dashboards", "dashboards.yml")
    assert os.path.exists(provider_path), f"Missing dashboard provider at {provider_path}"

    with open(provider_path, "r", encoding="utf-8") as f:
        provider_config = yaml.safe_load(f)

    assert "providers" in provider_config
    providers = provider_config["providers"]
    assert len(providers) >= 1
    assert any("/etc/grafana/provisioning/dashboards/definitions" in p.get("options", {}).get("path", "") for p in providers)


def test_grafana_dashboard_definition():
    """Verify Sceptic Observability dashboard JSON exists, parses as valid JSON, and has required panels."""
    dash_path = os.path.join(REPO_ROOT, "infra", "grafana", "dashboards", "definitions", "sceptic_observability.json")
    assert os.path.exists(dash_path), f"Missing Grafana dashboard at {dash_path}"

    with open(dash_path, "r", encoding="utf-8") as f:
        dashboard = json.load(f)

    assert dashboard.get("title") == "Sceptic - Target Service Observability"
    panels = dashboard.get("panels", [])
    assert len(panels) >= 6, "Dashboard must have panels for health, latency, rate, errors, and metadata"

    panel_titles = [p.get("title", "") for p in panels]
    assert any("Health" in t or "Up" in t for t in panel_titles)
    assert any("Error" in t for t in panel_titles)
    assert any("Latency" in t or "p95" in t for t in panel_titles)
    assert any("Rate" in t or "Requests" in t for t in panel_titles)
    assert any("Release" in t or "Deployment" in t for t in panel_titles)


def test_docker_compose_observability_services():
    """Verify both standard and prod Docker Compose files declare prometheus and grafana services."""
    for comp_file in ["docker-compose.yml", os.path.join("infra", "docker-compose.prod.yml")]:
        full_path = os.path.join(REPO_ROOT, comp_file)
        assert os.path.exists(full_path), f"Missing {comp_file}"

        with open(full_path, "r", encoding="utf-8") as f:
            compose_cfg = yaml.safe_load(f)

        services = compose_cfg.get("services", {})
        assert "prometheus" in services, f"prometheus service missing in {comp_file}"
        assert "grafana" in services, f"grafana service missing in {comp_file}"
        assert "target-service" in services, f"target-service service missing in {comp_file}"

        # Check port mappings or configurations
        prom_svc = services["prometheus"]
        graf_svc = services["grafana"]
        assert any("9090" in str(p) for p in prom_svc.get("ports", []))
        assert any("3000" in str(p) for p in graf_svc.get("ports", []))


def test_metrics_simulation_and_scrape():
    """Test full cycle of traffic simulation, error simulation, and metrics scrape."""
    client = TestClient(app)

    # 1. Warm up traffic
    r1 = client.get("/health")
    assert r1.status_code == 200

    r2 = client.get("/version")
    assert r2.status_code == 200

    r3 = client.get("/api/demo")
    assert r3.status_code == 200

    r4 = client.get("/api/fail?code=503")
    assert r4.status_code == 503

    # 2. Query /metrics
    metrics_res = client.get("/metrics")
    assert metrics_res.status_code == 200
    metrics_body = metrics_res.text

    # 3. Assertions on scraped output
    assert "http_requests_total" in metrics_body
    assert 'status_code="503"' in metrics_body
    assert 'status_code="200"' in metrics_body
    assert "http_request_duration_seconds_bucket" in metrics_body
    assert "target_service_app_info" in metrics_body
