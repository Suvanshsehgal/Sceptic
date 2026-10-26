"""
Sceptic Rollback Agent.
Responsible for safe, idempotent, auditable post-deployment recovery.

Answers:
"How can we safely and reliably recover a running deployment to a known-good state when failure or drift occurs?"

Workflow:
1. Validate deployment and operational justification
2. Discover previous known-good deployment
3. Verify comprehensive safety checks:
   - Target deployment validity & identity
   - Environment compatibility
   - Image metadata & availability
   - Database migration safety
   - Rollback concurrency lock
4. If safety checks fail: STOP + LOG + persist ABORTED record without modifying runtime
5. If safety checks pass: Acquire lock (IN_PROGRESS) -> Execute rollback
6. Post-rollback verification:
   - Wait for service ready
   - Health verification (/health)
   - Version & Commit SHA verification (/version)
   - State alignment (mark failed as ROLLED_BACK, target as ACTIVE, resolve drift events)
7. Persist complete audit record in rollback_records table
"""
import os
import shlex
import logging
import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy import select, and_, or_
from sqlalchemy.ext.asyncio import AsyncSession

import models
import schemas
from alerts import dispatch_alert
from app_config import get_settings


logger = logging.getLogger("sceptic.rollback")


class RollbackExecutor:
    """
    Abstract executor interface responsible for switching the running container / service.
    """
    async def execute(self, deployment: models.Deployment, target_deployment: models.Deployment) -> bool:
        raise NotImplementedError


class RollbackExecutorNotConfigured(RuntimeError):
    """Raised when no rollback command is configured, so no service was switched."""


class DefaultRollbackExecutor(RollbackExecutor):
    """
    Switches the running service by running the operator-configured ROLLBACK_COMMAND.

    The command is split with shlex and run without a shell. These placeholders are filled in:
    {commit_sha}, {image_name}, {image_tag}, {environment}, {deployment_id}, {target_deployment_id}.
    Example: ROLLBACK_COMMAND="python scripts/switch_image.py --image {image_name}:{image_tag}"

    Without ROLLBACK_COMMAND nothing is switched, and the rollback is recorded as FAILED.
    """
    def __init__(self, target_url: Optional[str] = None):
        settings = get_settings()
        self.target_url = (target_url or settings.TARGET_SERVICE_URL).rstrip("/")

    async def execute(self, deployment: models.Deployment, target_deployment: models.Deployment) -> bool:
        logger.info(
            f"Executing rollback from deployment {deployment.id} ({deployment.commit_sha}) "
            f"to target deployment {target_deployment.id} ({target_deployment.commit_sha})"
        )
        template = os.getenv("ROLLBACK_COMMAND", "").strip()
        if not template:
            raise RollbackExecutorNotConfigured(
                "ROLLBACK_COMMAND is not set. No service was switched, so the rollback was not performed."
            )

        values = {
            "commit_sha": target_deployment.commit_sha,
            "image_name": target_deployment.image_name,
            "image_tag": target_deployment.image_tag,
            "environment": target_deployment.environment,
            "deployment_id": str(deployment.id),
            "target_deployment_id": str(target_deployment.id),
        }
        argv = [part.format(**values) for part in shlex.split(template)]
        timeout = get_settings().ROLLBACK_COMMAND_TIMEOUT

        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.communicate()
            raise RuntimeError(f"Rollback command timed out after {timeout} seconds.")

        if proc.returncode != 0:
            tail = (stderr or stdout or b"").decode("utf-8", errors="replace").strip()[-500:]
            raise RuntimeError(f"Rollback command exited with code {proc.returncode}: {tail}")

        await asyncio.sleep(get_settings().ROLLBACK_SERVICE_READY_WAIT)
        return True


class RollbackAgent:
    """
    Autonomous and deterministic recovery agent enforcing strict safety principles
    prior to executing any deployment rollback.
    """

    def __init__(
        self,
        target_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None,
        executor: Optional[RollbackExecutor] = None,
        health_timeout: Optional[float] = None,
        poll_interval: Optional[float] = None
    ):
        settings = get_settings()
        self.target_url = (target_url or settings.TARGET_SERVICE_URL).rstrip("/")
        self._external_client = client
        self.executor = executor or DefaultRollbackExecutor(self.target_url)
        self.health_timeout = health_timeout or settings.ROLLBACK_HEALTH_TIMEOUT
        self.poll_interval = poll_interval or settings.ROLLBACK_POLL_INTERVAL

    async def _get_client(self) -> Tuple[httpx.AsyncClient, bool]:
        if self._external_client is not None:
            return self._external_client, False
        return httpx.AsyncClient(), True

    # ========================================================
    # STEP 1: VALIDATE DEPLOYMENT & DECISION JUSTIFICATION
    # ========================================================
    async def validate_deployment_and_decision(
        self,
        deployment: models.Deployment,
        reason: str,
        trigger_source: str,
        db: AsyncSession
    ) -> Tuple[bool, str]:
        """
        Validates that the deployment is eligible for rollback and the operational
        justification is legitimate and non-empty.
        """
        if deployment.status == "ROLLED_BACK":
            return False, "Deployment is already marked ROLLED_BACK. Cannot roll back an inactive deployment."

        if not reason or len(reason.strip()) < 3:
            return False, "Rollback justification reason is mandatory and must be at least 3 characters."

        valid_sources = {"MANUAL", "WATCHDOG", "GATEKEEPER", "AUTOMATED", "CI_CD"}
        if trigger_source.upper() not in valid_sources:
            return False, f"Invalid trigger_source '{trigger_source}'. Must be one of {valid_sources}."

        return True, "Deployment and operational justification validated successfully."

    # ========================================================
    # STEP 2: FIND PREVIOUS KNOWN-GOOD DEPLOYMENT
    # ========================================================
    async def find_previous_deployment(
        self,
        deployment: models.Deployment,
        db: AsyncSession,
        explicit_target_id: Optional[UUID] = None
    ) -> Tuple[Optional[models.Deployment], Optional[str]]:
        """
        Discovers the candidate target deployment to restore.
        Priority:
        1. Explicit target deployment ID if provided by requester
        2. Deployment's recorded previous_deployment_id
        3. Most recent preceding deployment in the same project with non-failed status
        """
        if explicit_target_id:
            if explicit_target_id == deployment.id:
                return None, "Target deployment cannot be the current deployment itself."

            stmt = select(models.Deployment).filter(
                models.Deployment.id == explicit_target_id,
                models.Deployment.project_id == deployment.project_id
            )
            res = await db.execute(stmt)
            target = res.scalars().first()
            if not target:
                return None, f"Specified target deployment {explicit_target_id} does not exist in this project."
            return target, None

        # 2. Check deployment.previous_deployment_id
        if deployment.previous_deployment_id:
            stmt = select(models.Deployment).filter(
                models.Deployment.id == deployment.previous_deployment_id,
                models.Deployment.project_id == deployment.project_id
            )
            res = await db.execute(stmt)
            target = res.scalars().first()
            if target and target.status != "FAILED":
                return target, None

        # 3. Discovery query: most recent deployment in same project deployed prior to current
        stmt = (
            select(models.Deployment)
            .filter(
                models.Deployment.project_id == deployment.project_id,
                models.Deployment.id != deployment.id,
                models.Deployment.created_at < deployment.created_at,
                models.Deployment.status.in_(["ACTIVE", "HEALTHY", "SUCCESS", "ROLLED_BACK"])
            )
            .order_by(models.Deployment.created_at.desc())
        )
        res = await db.execute(stmt)
        candidate = res.scalars().first()

        if candidate:
            return candidate, None

        # Fallback: any prior deployment regardless of status except FAILED
        stmt_fallback = (
            select(models.Deployment)
            .filter(
                models.Deployment.project_id == deployment.project_id,
                models.Deployment.id != deployment.id,
                models.Deployment.created_at < deployment.created_at,
                models.Deployment.status != "FAILED"
            )
            .order_by(models.Deployment.created_at.desc())
        )
        res_fallback = await db.execute(stmt_fallback)
        candidate_fallback = res_fallback.scalars().first()

        if candidate_fallback:
            return candidate_fallback, None

        return None, "No previous known-good deployment found for this project."

    async def _notify_rollback(
        self,
        deployment: models.Deployment,
        target: models.Deployment,
        record: models.RollbackRecord
    ) -> None:
        """Alerts on completed rollbacks (SUCCESS or FAILED). Best effort: a delivery problem never changes the outcome."""
        await dispatch_alert(
            title=f"Sceptic rollback {record.status} on {deployment.environment}",
            details={
                "deployment_id": str(deployment.id),
                "rolled_back_to": f"{target.commit_sha[:12]} ({target.id})",
                "trigger": record.trigger_source,
                "reason": record.reason,
                "error": record.error_message or "none",
            },
        )

    async def _find_active_rollback(
        self,
        project_id: UUID,
        db: AsyncSession,
        expire_stale: bool = False
    ) -> Optional[models.RollbackRecord]:
        """
        Returns a rollback that holds the project lock (IN_PROGRESS or PENDING).
        A record older than ROLLBACK_LOCK_TIMEOUT_SECONDS is stale (its run most likely crashed) and does not
        hold the lock. With expire_stale=True the stale records are also marked FAILED.
        """
        stmt = (
            select(models.RollbackRecord)
            .join(models.Deployment, models.RollbackRecord.deployment_id == models.Deployment.id)
            .filter(
                models.Deployment.project_id == project_id,
                models.RollbackRecord.status.in_(["IN_PROGRESS", "PENDING"])
            )
            .order_by(models.RollbackRecord.created_at.desc())
        )
        res = await db.execute(stmt)
        records = res.scalars().all()

        timeout_seconds = get_settings().ROLLBACK_LOCK_TIMEOUT_SECONDS
        cutoff = datetime.now(timezone.utc) - timedelta(seconds=timeout_seconds)
        active: Optional[models.RollbackRecord] = None
        expired_any = False
        for record in records:
            created = record.created_at
            if created is not None and created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            if created is not None and created < cutoff:
                if expire_stale:
                    record.status = "FAILED"
                    record.completed_at = datetime.now(timezone.utc)
                    record.error_message = f"Stale rollback lock expired after {timeout_seconds} seconds."
                    expired_any = True
                continue
            if active is None:
                active = record

        if expired_any:
            logger.warning(f"rollback_stale_lock_expired: project_id={project_id}")
        return active

    # ========================================================
    # STEP 3: SAFETY VERIFICATION
    # ========================================================
    async def verify_safety(
        self,
        deployment: models.Deployment,
        target_deployment: Optional[models.Deployment],
        db: AsyncSession,
        allow_unsafe_migration: bool = False
    ) -> Tuple[bool, Dict[str, Any], Optional[str]]:
        """
        Executes strict pre-flight safety checks:
        1. target_deployment_valid: target exists, belongs to project, distinct ID
        2. environment_compatibility: target environment matches current environment
        3. image_availability: target image_name and image_tag are valid and non-empty
        4. database_migration_safety: checks for destructive migration downgrade flags
        5. rollback_lock: verifies no concurrent rollback is in progress for this project
        """
        safety_checks: Dict[str, Any] = {}
        failure_reasons = []

        # Check 1: Target deployment validity
        if not target_deployment:
            safety_checks["target_deployment_valid"] = {
                "passed": False,
                "detail": "Target deployment is null or could not be found."
            }
            failure_reasons.append("Target deployment not found")
        elif target_deployment.project_id != deployment.project_id:
            safety_checks["target_deployment_valid"] = {
                "passed": False,
                "detail": f"Target deployment project mismatch: {target_deployment.project_id} != {deployment.project_id}"
            }
            failure_reasons.append("Target deployment belongs to a different project")
        elif target_deployment.id == deployment.id:
            safety_checks["target_deployment_valid"] = {
                "passed": False,
                "detail": "Target deployment cannot be identical to current deployment."
            }
            failure_reasons.append("Cannot roll back to the same deployment")
        else:
            safety_checks["target_deployment_valid"] = {
                "passed": True,
                "detail": f"Target deployment {target_deployment.id} belongs to project {deployment.project_id}."
            }

        # Check 2: Environment compatibility
        if target_deployment:
            if target_deployment.environment != deployment.environment:
                safety_checks["environment_compatibility"] = {
                    "passed": False,
                    "detail": (
                        f"Environment mismatch: target is '{target_deployment.environment}', "
                        f"current is '{deployment.environment}'."
                    )
                }
                failure_reasons.append("Environment mismatch: target is incompatible with current deployment environment")
            else:
                safety_checks["environment_compatibility"] = {
                    "passed": True,
                    "detail": f"Environment '{deployment.environment}' matches target environment."
                }
        else:
            safety_checks["environment_compatibility"] = {
                "passed": False,
                "detail": "Cannot evaluate environment without valid target deployment."
            }
            failure_reasons.append("Missing target deployment for environment check")

        # Check 3: Image availability and metadata
        if target_deployment:
            if not target_deployment.image_name or not target_deployment.image_tag:
                safety_checks["image_availability"] = {
                    "passed": False,
                    "detail": "Target deployment missing image_name or image_tag metadata."
                }
                failure_reasons.append("Target deployment image metadata missing")
            else:
                safety_checks["image_availability"] = {
                    "passed": True,
                    "detail": f"Target container image verified: {target_deployment.image_name}:{target_deployment.image_tag}"
                }
        else:
            safety_checks["image_availability"] = {
                "passed": False,
                "detail": "Cannot verify image availability without target deployment."
            }
            failure_reasons.append("Missing target deployment for image check")

        # Check 4: Database migration safety
        # If target deployment or deployment has explicit unsafe migration indicators
        has_unsafe_migration = False
        if deployment.version and target_deployment and target_deployment.version:
            # Check if reason explicitly mentions destructive migration or breaking schema
            if "breaking_schema" in (deployment.version or "").lower():
                has_unsafe_migration = True

        if has_unsafe_migration and not allow_unsafe_migration:
            safety_checks["database_migration_safety"] = {
                "passed": False,
                "detail": "Unsafe database migration downgrade detected. Requires manual override (allow_unsafe_migration=True)."
            }
            failure_reasons.append("Unsafe database migration downgrade")
        else:
            override_note = " (override permitted)" if has_unsafe_migration and allow_unsafe_migration else ""
            safety_checks["database_migration_safety"] = {
                "passed": True,
                "detail": f"Database migration safety verified{override_note}."
            }

        # Check 5: Rollback Concurrency Lock
        # Ensure no active rollback is currently IN_PROGRESS or PENDING for this project
        active_rollback = await self._find_active_rollback(deployment.project_id, db)

        if active_rollback:
            safety_checks["rollback_lock"] = {
                "passed": False,
                "detail": (
                    f"Rollback lock acquisition failed: Concurrent rollback operation {active_rollback.id} "
                    f"is currently {active_rollback.status} on this project."
                )
            }
            failure_reasons.append(f"Concurrent rollback operation in progress ({active_rollback.id})")
        else:
            safety_checks["rollback_lock"] = {
                "passed": True,
                "detail": "Rollback lock acquired successfully."
            }

        is_safe = len(failure_reasons) == 0
        error_msg = "; ".join(failure_reasons) if failure_reasons else None
        return is_safe, safety_checks, error_msg

    # ========================================================
    # DRY RUN / SAFETY EVALUATION
    # ========================================================
    async def evaluate_safety(
        self,
        deployment: models.Deployment,
        reason: str,
        trigger_source: str,
        db: AsyncSession,
        explicit_target_id: Optional[UUID] = None,
        allow_unsafe_migration: bool = False
    ) -> schemas.RollbackSafetyEvaluationResponse:
        """
        Evaluates rollback safety without acquiring locks or executing recovery.
        """
        valid, val_msg = await self.validate_deployment_and_decision(deployment, reason, trigger_source, db)
        if not valid:
            return schemas.RollbackSafetyEvaluationResponse(
                deployment_id=deployment.id,
                target_deployment_id=explicit_target_id,
                is_safe=False,
                safety_checks={
                    "decision_validation": {"passed": False, "detail": val_msg}
                },
                message=f"Validation failed: {val_msg}"
            )

        target, find_err = await self.find_previous_deployment(deployment, db, explicit_target_id)
        is_safe, safety_checks, err_msg = await self.verify_safety(
            deployment=deployment,
            target_deployment=target,
            db=db,
            allow_unsafe_migration=allow_unsafe_migration
        )

        msg = "Rollback pre-flight safety checks PASSED." if is_safe else f"Rollback safety checks FAILED: {err_msg}"
        return schemas.RollbackSafetyEvaluationResponse(
            deployment_id=deployment.id,
            target_deployment_id=target.id if target else None,
            target_commit_sha=target.commit_sha if target else None,
            target_image=f"{target.image_name}:{target.image_tag}" if target else None,
            is_safe=is_safe,
            safety_checks=safety_checks,
            message=msg
        )

    # ========================================================
    # STEP 5 & 6: POST-ROLLBACK HEALTH & VERSION VERIFICATION
    # ========================================================
    async def verify_recovered_service(
        self,
        target_deployment: models.Deployment,
        client: httpx.AsyncClient
    ) -> Tuple[bool, Optional[Dict[str, Any]], Optional[str]]:
        """
        Polls target application /health and /version endpoints to verify recovery.
        Ensures HTTP 200, healthy status, and exact commit SHA match.
        """
        health_url = f"{self.target_url}/health"
        version_url = f"{self.target_url}/version"
        deadline = asyncio.get_event_loop().time() + self.health_timeout

        last_error = "Target service did not become healthy within timeout window."
        version_metadata = None

        logger.info(
            f"Verifying recovered service at {self.target_url} "
            f"(expected commit: {target_deployment.commit_sha}, timeout: {self.health_timeout}s)"
        )

        while asyncio.get_event_loop().time() < deadline:
            try:
                # 1. Health Probe
                h_resp = await client.get(health_url, timeout=5.0)
                if h_resp.status_code != 200 or h_resp.json().get("status") != "healthy":
                    last_error = f"Health endpoint returned HTTP {h_resp.status_code}: {h_resp.text}"
                    await asyncio.sleep(self.poll_interval)
                    continue

                # 2. Version & Commit SHA Probe
                v_resp = await client.get(version_url, timeout=5.0)
                if v_resp.status_code != 200:
                    last_error = f"Version endpoint returned HTTP {v_resp.status_code}: {v_resp.text}"
                    await asyncio.sleep(self.poll_interval)
                    continue

                version_metadata = v_resp.json()
                running_commit = version_metadata.get("commit_sha")

                if running_commit != target_deployment.commit_sha:
                    last_error = (
                        f"Commit SHA mismatch post-rollback! Expected '{target_deployment.commit_sha}', "
                        f"observed '{running_commit}'."
                    )
                    logger.error(last_error)
                    return False, version_metadata, last_error

                logger.info(
                    f"Rollback verification SUCCESS: target running version "
                    f"'{version_metadata.get('version')}' (commit '{running_commit}')"
                )
                return True, version_metadata, None

            except Exception as e:
                last_error = f"Connection error probing service at {self.target_url}: {str(e)}"
                await asyncio.sleep(self.poll_interval)

        return False, version_metadata, last_error

    # ========================================================
    # FULL EXECUTION WORKFLOW
    # ========================================================
    async def evaluate_and_execute(
        self,
        deployment: models.Deployment,
        reason: str,
        trigger_source: str,
        db: AsyncSession,
        explicit_target_id: Optional[UUID] = None,
        allow_unsafe_migration: bool = False
    ) -> schemas.RollbackExecutionResponse:
        """
        Full end-to-end rollback recovery operation:
        1. Validate decision
        2. Discover target deployment
        3. Verify safety checks
        4. If unsafe: STOP + log + persist ABORTED record
        5. If safe: Acquire lock -> Execute rollback -> Verify health & version
        6. Persist final result (SUCCESS or FAILED) and align deployment state
        """
        now = datetime.now(timezone.utc)
        logger.info(
            f"rollback_requested: deployment_id={deployment.id} "
            f"source={trigger_source} reason='{reason}'"
        )

        # 1. Validate Decision
        valid, val_msg = await self.validate_deployment_and_decision(deployment, reason, trigger_source, db)
        if not valid:
            aborted_record = models.RollbackRecord(
                deployment_id=deployment.id,
                target_deployment_id=explicit_target_id,
                reason=reason,
                trigger_source=trigger_source,
                status="ABORTED",
                safety_check_result={"decision_validation": {"passed": False, "detail": val_msg}},
                started_at=now,
                completed_at=now,
                error_message=f"Validation failed: {val_msg}"
            )
            db.add(aborted_record)
            await db.commit()
            await db.refresh(aborted_record)

            return schemas.RollbackExecutionResponse(
                rollback_record=schemas.RollbackRecordResponse.model_validate(aborted_record),
                status="ABORTED",
                success=False,
                deployment_id=deployment.id,
                target_deployment_id=explicit_target_id,
                safety_checks={"decision_validation": {"passed": False, "detail": val_msg}},
                message=f"Rollback aborted: {val_msg}"
            )

        # 2. Find Previous Deployment
        target, find_err = await self.find_previous_deployment(deployment, db, explicit_target_id)

        # 3. Safety Verification
        is_safe, safety_checks, safety_err = await self.verify_safety(
            deployment=deployment,
            target_deployment=target,
            db=db,
            allow_unsafe_migration=allow_unsafe_migration
        )

        # 4. If Safety Verification Fails -> STOP + LOG + PERSIST
        if not is_safe:
            logger.warning(
                f"rollback_safety_check_failed: deployment_id={deployment.id} "
                f"target_id={target.id if target else None} reason='{safety_err}'"
            )
            aborted_record = models.RollbackRecord(
                deployment_id=deployment.id,
                target_deployment_id=target.id if target else explicit_target_id,
                reason=reason,
                trigger_source=trigger_source,
                status="ABORTED",
                safety_check_result=safety_checks,
                started_at=now,
                completed_at=now,
                error_message=f"Safety checks failed: {safety_err}"
            )
            db.add(aborted_record)
            await db.commit()
            await db.refresh(aborted_record)

            return schemas.RollbackExecutionResponse(
                rollback_record=schemas.RollbackRecordResponse.model_validate(aborted_record),
                status="ABORTED",
                success=False,
                deployment_id=deployment.id,
                target_deployment_id=target.id if target else explicit_target_id,
                safety_checks=safety_checks,
                message=f"Rollback aborted by safety controller: {safety_err}"
            )

        # 5. Acquire Lock & Mark IN_PROGRESS
        # Lock the project row so two rollbacks on the same project cannot both pass the check above.
        # The row lock is held until the commit that inserts the IN_PROGRESS record.
        await db.execute(
            select(models.Project.id)
            .filter(models.Project.id == deployment.project_id)
            .with_for_update()
        )
        concurrent = await self._find_active_rollback(deployment.project_id, db, expire_stale=True)
        if concurrent is not None:
            safety_checks["rollback_lock"] = {
                "passed": False,
                "detail": (
                    f"Rollback lock acquisition failed: Concurrent rollback operation {concurrent.id} "
                    f"is currently {concurrent.status} on this project."
                )
            }
            aborted_record = models.RollbackRecord(
                deployment_id=deployment.id,
                target_deployment_id=target.id,
                reason=reason,
                trigger_source=trigger_source,
                status="ABORTED",
                safety_check_result=safety_checks,
                started_at=now,
                completed_at=datetime.now(timezone.utc),
                error_message=f"Safety checks failed: Concurrent rollback operation {concurrent.id} is in progress"
            )
            db.add(aborted_record)
            await db.commit()
            await db.refresh(aborted_record)
            return schemas.RollbackExecutionResponse(
                rollback_record=schemas.RollbackRecordResponse.model_validate(aborted_record),
                status="ABORTED",
                success=False,
                deployment_id=deployment.id,
                target_deployment_id=target.id,
                safety_checks=safety_checks,
                message=f"Rollback aborted by safety controller: concurrent rollback {concurrent.id} in progress"
            )

        logger.info(f"rollback_lock_acquired: deployment_id={deployment.id} target_id={target.id}")
        record = models.RollbackRecord(
            deployment_id=deployment.id,
            target_deployment_id=target.id,
            reason=reason,
            trigger_source=trigger_source,
            status="IN_PROGRESS",
            safety_check_result=safety_checks,
            started_at=now
        )
        db.add(record)
        await db.commit()
        await db.refresh(record)

        client, should_close = await self._get_client()

        try:
            # 6. Execute Rollback
            try:
                exec_ok = await self.executor.execute(deployment, target)
                if not exec_ok:
                    raise RuntimeError("Rollback executor returned failure status.")
            except Exception as e:
                logger.error(f"rollback_execution_error: {e}")
                record.status = "FAILED"
                record.completed_at = datetime.now(timezone.utc)
                record.error_message = f"Execution failure: {str(e)}"
                await db.commit()
                await db.refresh(record)
                await self._notify_rollback(deployment, target, record)

                return schemas.RollbackExecutionResponse(
                    rollback_record=schemas.RollbackRecordResponse.model_validate(record),
                    status="FAILED",
                    success=False,
                    deployment_id=deployment.id,
                    target_deployment_id=target.id,
                    safety_checks=safety_checks,
                    message=f"Rollback execution failed: {str(e)}"
                )

            # 7. Post-Rollback Health & Version Verification
            v_ok, v_metadata, v_err = await self.verify_recovered_service(target, client)

            if not v_ok:
                logger.error(f"rollback_verification_failed: {v_err}")
                record.status = "FAILED"
                record.completed_at = datetime.now(timezone.utc)
                record.error_message = f"Post-rollback verification failed: {v_err}"
                deployment.status = "FAILED"
                await db.commit()
                await db.refresh(record)
                await self._notify_rollback(deployment, target, record)

                return schemas.RollbackExecutionResponse(
                    rollback_record=schemas.RollbackRecordResponse.model_validate(record),
                    status="FAILED",
                    success=False,
                    deployment_id=deployment.id,
                    target_deployment_id=target.id,
                    safety_checks=safety_checks,
                    verification_details=v_metadata,
                    message=f"Service recovery failed post-rollback verification: {v_err}"
                )

            # 8. Success: Update Deployment State & Resolve Drift Events
            deployment.status = "ROLLED_BACK"
            target.status = "ACTIVE"
            target.completed_at = datetime.now(timezone.utc)

            # Resolve any active drift events on this deployment
            drift_stmt = select(models.DriftEvent).filter(
                models.DriftEvent.deployment_id == deployment.id,
                models.DriftEvent.resolved_at.is_(None)
            )
            drift_res = await db.execute(drift_stmt)
            for drift in drift_res.scalars().all():
                drift.resolved_at = datetime.now(timezone.utc)

            record.status = "SUCCESS"
            record.completed_at = datetime.now(timezone.utc)
            record.error_message = None

            await db.commit()
            await db.refresh(record)
            await self._notify_rollback(deployment, target, record)

            logger.info(
                f"rollback_succeeded: deployment_id={deployment.id} "
                f"target_id={target.id} running_commit={target.commit_sha}"
            )

            return schemas.RollbackExecutionResponse(
                rollback_record=schemas.RollbackRecordResponse.model_validate(record),
                status="SUCCESS",
                success=True,
                deployment_id=deployment.id,
                target_deployment_id=target.id,
                safety_checks=safety_checks,
                verification_details=v_metadata,
                message=(
                    f"Rollback completed successfully. Target service restored to "
                    f"deployment {target.id} (commit {target.commit_sha}, version {target.version})."
                )
            )

        finally:
            if should_close:
                await client.aclose()
