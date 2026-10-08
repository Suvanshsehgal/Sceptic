"""
Sceptic Deployment Gatekeeper.
Responsible for deployment integrity and configuration drift verification.

Answers:
"Is the application currently running actually the deployment/artifact/configuration that was intended to be deployed?"

Verifies:
1. Running Commit SHA vs Expected Deployment Commit SHA
2. Running Application Version vs Expected Application Version
3. Running Environment vs Expected Environment
4. Image Identity / Digest (returns UNRESOLVED if digest is unavailable; never guesses)
5. Service Reachability & Deployment State Alignment (ACTIVE DB state vs live runtime)
6. Idempotent Drift Event Persistence (no duplicate active drift events created on repeated checks)
7. Structured Findings (COMMIT_MISMATCH, VERSION_MISMATCH, ENVIRONMENT_MISMATCH, IMAGE_MISMATCH, DEPLOYMENT_STATE_MISMATCH, UNRESOLVED)

CRITICAL: NO ROLLBACK OR RECOVERY IS PERFORMED.
"""
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import models
import schemas
from app_config import get_settings


logger = logging.getLogger("sceptic.gatekeeper")


class DeploymentGatekeeper:
    """
    Deterministic verification component evaluating deployment integrity.
    """

    def __init__(
        self,
        target_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None
    ):
        settings = get_settings()
        self.target_url = (target_url or settings.TARGET_SERVICE_URL).rstrip("/")
        self._external_client = client

    async def _get_client(self) -> Tuple[httpx.AsyncClient, bool]:
        if self._external_client is not None:
            return self._external_client, False
        return httpx.AsyncClient(), True

    async def _persist_drift_idempotent(
        self,
        db: AsyncSession,
        deployment_id: UUID,
        drift_type: str,
        expected_val: str,
        actual_val: str,
        severity: str,
        description: str
    ) -> bool:
        """
        Persists a drift event only if an unresolved drift event with identical
        type, expected value, and actual value does not already exist.
        Returns True if a new event was created, False if skipped.
        """
        stmt = (
            select(models.DriftEvent)
            .filter(
                models.DriftEvent.deployment_id == deployment_id,
                models.DriftEvent.drift_type == drift_type,
                models.DriftEvent.expected_value == expected_val,
                models.DriftEvent.actual_value == actual_val,
                models.DriftEvent.resolved_at.is_(None)
            )
        )
        res = await db.execute(stmt)
        existing = res.scalars().first()

        if existing:
            logger.info(
                f"Skipping duplicate drift event: deployment_id={deployment_id} "
                f"drift_type={drift_type} (already tracked in id={existing.id})"
            )
            return False

        drift = models.DriftEvent(
            deployment_id=deployment_id,
            drift_type=drift_type,
            expected_value=expected_val,
            actual_value=actual_val,
            severity=severity,
            description=description,
            detected_at=datetime.now(timezone.utc)
        )
        db.add(drift)
        await db.commit()
        await db.refresh(drift)
        logger.warning(
            f"deployment_drift_detected: deployment_id={deployment_id} "
            f"drift_type={drift_type} severity={severity}"
        )
        return True

    async def evaluate(
        self,
        deployment: models.Deployment,
        db: AsyncSession
    ) -> schemas.GatekeeperCheckResult:
        """
        Executes deterministic integrity checks comparing desired deployment state against live target.
        """
        client, should_close = await self._get_client()
        settings = get_settings()
        logger.info(f"gatekeeper_check_started: deployment_id={deployment.id} project_id={deployment.project_id}")

        findings: List[schemas.GatekeeperFinding] = []
        drift_events_created = 0

        try:
            # 1. Reachability & Basic Health Check
            health_url = f"{self.target_url}/health"
            is_healthy = False
            try:
                h_resp = await client.get(health_url, timeout=settings.WATCHDOG_HEALTH_TIMEOUT)
                if h_resp.status_code == 200 and h_resp.json().get("status") == "healthy":
                    is_healthy = True
                else:
                    findings.append(schemas.GatekeeperFinding(
                        finding_type="HEALTH_FAILURE",
                        severity="CRITICAL",
                        expected_value="healthy",
                        actual_value=f"HTTP {h_resp.status_code}",
                        description=f"Target service /health returned non-healthy response: {h_resp.text}",
                        detected_at=datetime.now(timezone.utc)
                    ))
            except Exception as e:
                findings.append(schemas.GatekeeperFinding(
                    finding_type="HEALTH_FAILURE",
                    severity="CRITICAL",
                    expected_value="Reachable service",
                    actual_value=f"Connection failure: {type(e).__name__}",
                    description=f"Target service unreachable at {health_url}: {str(e)}",
                    detected_at=datetime.now(timezone.utc)
                ))

            # If service is marked ACTIVE in database but unhealthy in reality, record DEPLOYMENT_STATE_MISMATCH
            if deployment.status == "ACTIVE" and not is_healthy:
                desc = "Deployment status is ACTIVE in database, but running service is unreachable or unhealthy."
                findings.append(schemas.GatekeeperFinding(
                    finding_type="DEPLOYMENT_STATE_MISMATCH",
                    severity="CRITICAL",
                    expected_value="ACTIVE & Healthy",
                    actual_value="Unhealthy / Unreachable",
                    description=desc,
                    detected_at=datetime.now(timezone.utc)
                ))
                created = await self._persist_drift_idempotent(
                    db=db,
                    deployment_id=deployment.id,
                    drift_type="CONFIGURATION",
                    expected_val="ACTIVE (Healthy)",
                    actual_val="Unhealthy",
                    severity="CRITICAL",
                    description=desc
                )
                if created:
                    drift_events_created += 1

            # 2. Runtime Version & Deployment Metadata Check
            version_url = f"{self.target_url}/version"
            runtime_meta: Optional[Dict[str, Any]] = None
            try:
                v_resp = await client.get(version_url, timeout=settings.WATCHDOG_HEALTH_TIMEOUT)
                if v_resp.status_code == 200:
                    runtime_meta = v_resp.json()
                else:
                    findings.append(schemas.GatekeeperFinding(
                        finding_type="UNRESOLVED",
                        severity="MEDIUM",
                        expected_value="HTTP 200 from /version",
                        actual_value=f"HTTP {v_resp.status_code}",
                        description=f"/version endpoint returned HTTP {v_resp.status_code}",
                        detected_at=datetime.now(timezone.utc)
                    ))
            except Exception as e:
                findings.append(schemas.GatekeeperFinding(
                    finding_type="UNRESOLVED",
                    severity="HIGH",
                    expected_value="Reachable /version endpoint",
                    actual_value=f"Connection failure: {type(e).__name__}",
                    description=f"Failed to query /version endpoint: {str(e)}",
                    detected_at=datetime.now(timezone.utc)
                ))

            if runtime_meta is not None:
                actual_commit = runtime_meta.get("commit_sha")
                actual_version = runtime_meta.get("version")
                actual_env = runtime_meta.get("environment")

                # 3. Commit SHA Verification
                if actual_commit is None:
                    findings.append(schemas.GatekeeperFinding(
                        finding_type="UNRESOLVED",
                        severity="MEDIUM",
                        expected_value=deployment.commit_sha,
                        actual_value="None",
                        description="Runtime metadata missing 'commit_sha' key.",
                        detected_at=datetime.now(timezone.utc)
                    ))
                elif actual_commit != deployment.commit_sha:
                    desc = f"Running commit '{actual_commit}' does not match expected deployment commit '{deployment.commit_sha}'."
                    findings.append(schemas.GatekeeperFinding(
                        finding_type="COMMIT_MISMATCH",
                        severity="CRITICAL",
                        expected_value=deployment.commit_sha,
                        actual_value=actual_commit,
                        description=desc,
                        detected_at=datetime.now(timezone.utc)
                    ))
                    created = await self._persist_drift_idempotent(
                        db=db,
                        deployment_id=deployment.id,
                        drift_type="COMMIT",
                        expected_val=deployment.commit_sha,
                        actual_val=actual_commit,
                        severity="CRITICAL",
                        description=desc
                    )
                    if created:
                        drift_events_created += 1

                # 4. Application Version Verification
                if deployment.version:
                    if actual_version is None:
                        findings.append(schemas.GatekeeperFinding(
                            finding_type="UNRESOLVED",
                            severity="LOW",
                            expected_value=deployment.version,
                            actual_value="None",
                            description="Runtime metadata missing 'version' key.",
                            detected_at=datetime.now(timezone.utc)
                        ))
                    elif actual_version != deployment.version:
                        desc = f"Running version '{actual_version}' does not match expected version '{deployment.version}'."
                        findings.append(schemas.GatekeeperFinding(
                            finding_type="VERSION_MISMATCH",
                            severity="HIGH",
                            expected_value=deployment.version,
                            actual_value=actual_version,
                            description=desc,
                            detected_at=datetime.now(timezone.utc)
                        ))
                        created = await self._persist_drift_idempotent(
                            db=db,
                            deployment_id=deployment.id,
                            drift_type="CONFIGURATION",
                            expected_val=deployment.version,
                            actual_val=actual_version,
                            severity="HIGH",
                            description=desc
                        )
                        if created:
                            drift_events_created += 1

                # 5. Environment Verification
                if deployment.environment and actual_env:
                    if actual_env.lower() != deployment.environment.lower():
                        desc = f"Running environment '{actual_env}' does not match expected '{deployment.environment}'."
                        findings.append(schemas.GatekeeperFinding(
                            finding_type="ENVIRONMENT_MISMATCH",
                            severity="HIGH",
                            expected_value=deployment.environment,
                            actual_value=actual_env,
                            description=desc,
                            detected_at=datetime.now(timezone.utc)
                        ))
                        created = await self._persist_drift_idempotent(
                            db=db,
                            deployment_id=deployment.id,
                            drift_type="ENVIRONMENT",
                            expected_val=deployment.environment,
                            actual_val=actual_env,
                            severity="HIGH",
                            description=desc
                        )
                        if created:
                            drift_events_created += 1

                # 6. Image Identity / Digest Verification
                # In Docker without container socket access, image digest cannot be reliably obtained from /version.
                # Must return UNRESOLVED instead of guessing or returning a fake PASS.
                actual_digest = runtime_meta.get("image_digest")
                if deployment.image_digest and actual_digest:
                    if actual_digest != deployment.image_digest:
                        desc = f"Running image digest '{actual_digest}' does not match expected '{deployment.image_digest}'."
                        findings.append(schemas.GatekeeperFinding(
                            finding_type="IMAGE_MISMATCH",
                            severity="HIGH",
                            expected_value=deployment.image_digest,
                            actual_value=actual_digest,
                            description=desc,
                            detected_at=datetime.now(timezone.utc)
                        ))
                        created = await self._persist_drift_idempotent(
                            db=db,
                            deployment_id=deployment.id,
                            drift_type="IMAGE_DIGEST",
                            expected_val=deployment.image_digest,
                            actual_val=actual_digest,
                            severity="HIGH",
                            description=desc
                        )
                        if created:
                            drift_events_created += 1
                else:
                    findings.append(schemas.GatekeeperFinding(
                        finding_type="UNRESOLVED",
                        severity="LOW",
                        expected_value=deployment.image_digest or "Verified Digest",
                        actual_value="Unavailable",
                        description="Runtime image digest unavailable from target service metadata.",
                        detected_at=datetime.now(timezone.utc)
                    ))

            # 7. Overall Status Evaluation
            has_failures = any(
                f.severity in ("CRITICAL", "HIGH") and f.finding_type != "UNRESOLVED"
                for f in findings
            )
            has_unresolved = any(
                f.finding_type == "UNRESOLVED"
                for f in findings
            )

            if has_failures:
                overall_status = schemas.VerificationStatus.FAIL
                summary = f"Gatekeeper detected {len(findings)} finding(s) with deployment drift or mismatches."
            elif has_unresolved:
                overall_status = schemas.VerificationStatus.UNRESOLVED
                summary = f"Gatekeeper completed with unresolved artifact attributes."
            else:
                overall_status = schemas.VerificationStatus.PASS
                summary = "All gatekeeper deployment integrity checks passed successfully."

            logger.info(
                f"gatekeeper_check_completed: deployment_id={deployment.id} "
                f"status={overall_status} drift_events_created={drift_events_created}"
            )

            return schemas.GatekeeperCheckResult(
                deployment_id=deployment.id,
                status=overall_status,
                checked_at=datetime.now(timezone.utc),
                findings=findings,
                drift_events_created=drift_events_created,
                summary=summary
            )

        finally:
            if should_close:
                await client.aclose()
