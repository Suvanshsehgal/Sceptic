"""
Phase 4 demo: break the demo site, let the Watchdog detect it, run the A2A chain, and save a Markdown report.

Prerequisites (see demo/README.md):
- Stack running: docker compose up -d --build demo-site prometheus grafana backend
- Demo control panel running on port 8091
- The backend's TARGET_SERVICE_URL points at the demo site (http://demo-site:8090 inside compose), because
  the Watchdog probes that URL.
- A Sceptic login token and the UUID of a deployment owned by that user.

Usage:
    set SCEPTIC_TOKEN=<bearer token>
    python scripts/demo_post_deploy.py --deployment-id <uuid>

The script always resets the injected fault at the end, even when a step fails.
"""
import argparse
import os
import sys
import time
from pathlib import Path

import httpx

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

import a2a_subset as a2a  # noqa: E402  (the A2A helpers live in backend/)


def inject_fault(control: httpx.Client, error_rate: int, latency_ms: int = 0) -> None:
    resp = control.post("/api/fault", json={"error_rate": error_rate, "latency_ms": latency_ms})
    resp.raise_for_status()


def send_traffic(control: httpx.Client, total: int) -> None:
    remaining = total
    while remaining > 0:
        batch = min(remaining, 200)  # the control panel accepts at most 200 per call
        control.post("/api/traffic", json={"count": batch}).raise_for_status()
        remaining -= batch


def main() -> int:
    parser = argparse.ArgumentParser(description="Sceptic post-deployment demo")
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--backend", default=os.getenv("SCEPTIC_BACKEND_URL", "http://localhost:8000"))
    parser.add_argument("--control", default=os.getenv("DEMO_CONTROL_URL", "http://localhost:8091"))
    parser.add_argument("--requests", type=int, default=120, help="requests to send while the fault is active")
    parser.add_argument("--wait", type=int, default=20, help="seconds to wait for Prometheus to scrape")
    parser.add_argument("--report-dir", default=str(REPO_ROOT / "reports"))
    args = parser.parse_args()

    token = os.getenv("SCEPTIC_TOKEN")
    if not token:
        print("Set SCEPTIC_TOKEN to a Sceptic bearer token first.")
        return 2
    auth = {"Authorization": f"Bearer {token}"}

    with httpx.Client(base_url=args.control, timeout=60) as control, \
            httpx.Client(base_url=args.backend, timeout=120, headers=auth) as backend:
        try:
            print("1. Injecting 100% HTTP 500 errors into the demo site")
            inject_fault(control, error_rate=100)
            send_traffic(control, args.requests)

            print(f"2. Waiting {args.wait}s for Prometheus to scrape the new metrics")
            time.sleep(args.wait)

            print("3. Watchdog A2A check (Watchdog -> Rollback when FAIL)")
            resp = backend.post("/a2a/watchdog", json=a2a.make_request(
                {"deployment_id": args.deployment_id}, request_id="demo-watchdog"))
            resp.raise_for_status()
            data = a2a.response_data(resp.json())
            watch = data["watchdog"]
            print(f"   Watchdog verdict: {watch['status']}")
            for finding in watch["findings"]:
                print(f"   - {finding['finding_type']} ({finding['severity']}): {finding['description']}")
            rollback = data.get("rollback")
            if rollback is None:
                print("   Rollback agent was not called (no FAIL).")
            elif "error" in rollback:
                print(f"   Rollback A2A call failed: {rollback['error']}")
            else:
                result = rollback["rollback"]
                print(f"   Rollback agent status: {result['status']} (success={result['success']})")

            print("4. Saving the Markdown incident report")
            resp = backend.post(f"/deployments/{args.deployment_id}/report")
            resp.raise_for_status()
            report = resp.json()
            out_dir = Path(args.report_dir)
            out_dir.mkdir(parents=True, exist_ok=True)
            out_path = out_dir / report["report_name"]
            out_path.write_text(report["markdown"], encoding="utf-8")
            print(f"   Report written: {out_path} (LLM summary: {report['llm_used']})")
            return 0
        except httpx.HTTPError as exc:
            print(f"Demo step failed: {exc}")
            return 1
        finally:
            print("5. Resetting the demo site to healthy")
            try:
                inject_fault(control, error_rate=0)
            except httpx.HTTPError as exc:
                print(f"   Could not reset the fault, reset it in the control panel: {exc}")


if __name__ == "__main__":
    sys.exit(main())
