#!/usr/bin/env python3
"""
Sceptic Automated Deployment & Verification Runner (Phase 11).

Orchestrates:
1. Deployment Trust Gate validation (APPROVE required; BLOCK / REQUEST_CHANGES prevented).
2. Deployment record creation in PostgreSQL (status=DEPLOYING).
3. Target application health probe (/health) and version verification (/version).
4. Runtime commit SHA validation against expected deployment commit SHA.
5. Final deployment status persistence (status=ACTIVE or status=FAILED).
"""

import sys
import time
import argparse
import logging
from typing import Dict, Any, Optional, Tuple
from uuid import UUID

import httpx

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("sceptic.deployer")

MIN_OVERRIDE_REASON_LENGTH = 10


def evaluate_trust_gate(recommendation: Optional[str]) -> Tuple[bool, str]:
    """
    Evaluates Report Synthesizer recommendation against deployment gating policy.
    - APPROVE: deployment permitted
    - REQUEST_CHANGES: deployment prevented
    - BLOCK: deployment prevented
    """
    if not recommendation:
        # Fail closed: a deployment with no verification verdict is not verified.
        return False, "Deployment halted: no trust recommendation was provided, so the code is unverified."

    rec = recommendation.strip().upper()
    if rec == "APPROVE":
        return True, "Trust score check passed (Recommendation: APPROVE)."
    elif rec == "REQUEST_CHANGES":
        return False, "Deployment halted: Verification recommended REQUEST_CHANGES (Trust score < 85)."
    elif rec == "BLOCK":
        return False, "Deployment halted: Verification recommended BLOCK (Severe findings / Trust score < 65)."
    else:
        return False, f"Deployment halted: Unrecognized verification recommendation '{rec}'."


def verify_target_health(
    target_url: str,
    expected_commit_sha: str,
    timeout_seconds: float = 30.0,
    poll_interval: float = 2.0
) -> Tuple[bool, Optional[Dict[str, Any]], str]:
    """
    Polls target application's /health and /version endpoints.
    Verifies HTTP 200 and matches expected commit SHA against running commit SHA.
    """
    target_url = target_url.rstrip("/")
    health_url = f"{target_url}/health"
    version_url = f"{target_url}/version"
    deadline = time.time() + timeout_seconds

    logger.info(f"Initiating health & version verification at {target_url} (deadline: {timeout_seconds}s)")

    last_error = "Target did not respond within timeout window."

    while time.time() < deadline:
        try:
            with httpx.Client(timeout=5.0) as client:
                # 1. Health check
                h_resp = client.get(health_url)
                if h_resp.status_code != 200:
                    last_error = f"Health check returned HTTP {h_resp.status_code}: {h_resp.text}"
                    time.sleep(poll_interval)
                    continue

                h_data = h_resp.json()
                if h_data.get("status") != "healthy":
                    last_error = f"Health check payload status != 'healthy': {h_data}"
                    time.sleep(poll_interval)
                    continue

                # 2. Version and runtime metadata check
                v_resp = client.get(version_url)
                if v_resp.status_code != 200:
                    last_error = f"Version endpoint returned HTTP {v_resp.status_code}: {v_resp.text}"
                    time.sleep(poll_interval)
                    continue

                v_data = v_resp.json()
                running_commit = v_data.get("commit_sha")

                if running_commit != expected_commit_sha:
                    last_error = (
                        f"Commit SHA mismatch! Expected '{expected_commit_sha}', "
                        f"but target is running '{running_commit}'."
                    )
                    # Commit mismatch is a deterministic failure, fail immediately
                    logger.error(last_error)
                    return False, v_data, last_error

                logger.info(f"Health verification SUCCESS! Target running version {v_data.get('version')} (commit {running_commit})")
                return True, v_data, "Health and version verification passed."

        except Exception as e:
            last_error = f"Connection error: {str(e)}"
            time.sleep(poll_interval)

    logger.error(f"Health verification TIMEOUT: {last_error}")
    return False, None, last_error


def run_deployment_pipeline(
    project_id: str,
    commit_sha: str,
    image_name: str,
    image_tag: str,
    environment: str = "production",
    version: Optional[str] = "1.0.0",
    target_url: str = "http://localhost:8080",
    backend_url: str = "http://localhost:8000",
    api_token: Optional[str] = None,
    trust_recommendation: Optional[str] = None,
    timeout_seconds: float = 30.0,
    client: Optional[httpx.Client] = None,
    override_reason: Optional[str] = None,
    override_by: Optional[str] = None,
) -> Tuple[int, Dict[str, Any]]:
    """
    Full deployment orchestration executor.
    Returns (exit_code, result_dict).

    Gate override: a BLOCK or REQUEST_CHANGES verdict can be overridden only with a named approver
    (override_by) and a reason of at least MIN_OVERRIDE_REASON_LENGTH characters. The override is logged
    and returned in the result, so the deployment record shows who approved it.
    """
    backend_url = backend_url.rstrip("/")
    headers = {"Authorization": f"Bearer {api_token}"} if api_token else {}

    # Step 1: Trust Score Deployment Gate
    gate_ok, gate_msg = evaluate_trust_gate(trust_recommendation)
    override_record = None
    if not gate_ok:
        reason = (override_reason or "").strip()
        approver = (override_by or "").strip()
        if reason:
            if len(reason) < MIN_OVERRIDE_REASON_LENGTH or not approver:
                logger.error(
                    f"[GATE DENIED] {gate_msg} Override rejected: an approver and a reason of at least "
                    f"{MIN_OVERRIDE_REASON_LENGTH} characters are required."
                )
                return 1, {
                    "status": "BLOCKED",
                    "reason": f"{gate_msg} Override rejected: approver and reason are required.",
                    "commit_sha": commit_sha
                }
            override_record = {
                "approved_by": approver,
                "reason": reason,
                "trust_recommendation": trust_recommendation,
            }
            logger.warning(
                f"[GATE OVERRIDE] {gate_msg} Overridden by {approver}: {reason}"
            )
            gate_ok = True
            gate_msg = f"Gate overridden by {approver}."
    if not gate_ok:
        logger.error(f"[GATE DENIED] {gate_msg}")
        return 1, {
            "status": "BLOCKED",
            "reason": gate_msg,
            "commit_sha": commit_sha
        }
    logger.info(f"[GATE APPROVED] {gate_msg}")

    # Step 2: Register deployment record in DB (status=DEPLOYING)
    deployment_id = None
    http = client or httpx.Client(timeout=10.0)

    try:
        dep_payload = {
            "commit_sha": commit_sha,
            "image_name": image_name,
            "image_tag": image_tag,
            "environment": environment,
            "version": version,
            "status": "DEPLOYING"
        }
        res = http.post(f"{backend_url}/projects/{project_id}/deployments", json=dep_payload, headers=headers)
        if res.status_code == 201:
            dep_data = res.json()
            deployment_id = dep_data["id"]
            logger.info(f"Registered deployment {deployment_id} with status 'DEPLOYING'.")
        else:
            logger.warning(f"Could not persist deployment record (HTTP {res.status_code}): {res.text}")
    except Exception as e:
        logger.warning(f"Backend offline or unreachable for deployment record registration: {e}")

    # Step 3: Health & Version Verification
    success, v_data, reason = verify_target_health(
        target_url=target_url,
        expected_commit_sha=commit_sha,
        timeout_seconds=timeout_seconds
    )

    final_status = "ACTIVE" if success else "FAILED"

    # Step 4: Update deployment record in DB
    if deployment_id:
        try:
            update_payload = {
                "status": final_status,
                "completed_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            }
            res_up = http.patch(
                f"{backend_url}/deployments/{deployment_id}/status",
                json=update_payload,
                headers=headers
            )
            if res_up.status_code == 200:
                logger.info(f"Updated deployment {deployment_id} status to '{final_status}'.")
            else:
                logger.warning(f"Failed to update deployment status: {res_up.text}")
        except Exception as e:
            logger.warning(f"Failed to update deployment status in backend: {e}")

    exit_code = 0 if success else 1
    return exit_code, {
        "status": final_status,
        "deployment_id": deployment_id,
        "commit_sha": commit_sha,
        "image": f"{image_name}:{image_tag}",
        "reason": reason,
        "metadata": v_data,
        "gate_override": override_record,
    }


def main():
    parser = argparse.ArgumentParser(description="Sceptic CI/CD Automated Deployment Runner")
    parser.add_argument("--project-id", required=True, help="UUID of project being deployed")
    parser.add_argument("--commit-sha", required=True, help="Expected Git commit SHA to verify")
    parser.add_argument("--image-name", default="ghcr.io/suvanshsehgal/sceptic-target-service", help="Container image repository")
    parser.add_argument("--image-tag", default=None, help="Container image tag (defaults to commit SHA)")
    parser.add_argument("--environment", default="production", help="Deployment environment")
    parser.add_argument("--version", default="1.0.0", help="Application version string")
    parser.add_argument("--target-url", default="http://localhost:8080", help="Base URL of deployed target service")
    parser.add_argument("--backend-url", default="http://localhost:8000", help="Base URL of Sceptic backend API")
    parser.add_argument("--api-token", default=None, help="JWT bearer token for authenticated requests")
    parser.add_argument("--trust-recommendation", default=None, choices=["APPROVE", "REQUEST_CHANGES", "BLOCK"], help="Synthesizer recommendation")
    parser.add_argument("--timeout", type=float, default=30.0, help="Readiness check timeout in seconds")
    parser.add_argument("--override-reason", default=None, help="Justification for overriding a BLOCK or REQUEST_CHANGES gate (min 10 characters)")
    parser.add_argument("--override-by", default=None, help="Name of the person approving the gate override")

    args = parser.parse_args()

    image_tag = args.image_tag or args.commit_sha

    exit_code, result = run_deployment_pipeline(
        project_id=args.project_id,
        commit_sha=args.commit_sha,
        image_name=args.image_name,
        image_tag=image_tag,
        environment=args.environment,
        version=args.version,
        target_url=args.target_url,
        backend_url=args.backend_url,
        api_token=args.api_token,
        trust_recommendation=args.trust_recommendation,
        timeout_seconds=args.timeout,
        override_reason=args.override_reason,
        override_by=args.override_by,
    )

    print(f"Deployment Result: {result}")
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
