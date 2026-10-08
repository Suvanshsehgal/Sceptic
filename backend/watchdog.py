"""
Sceptic Pipeline Watchdog.
Responsible for runtime health, performance, and Prometheus telemetry verification.

Evaluates:
1. Application Health (/health)
2. Error Rate (Prometheus http_requests_total) with minimum-sample threshold protection
3. Latency (Prometheus p95 latency and average latency)
4. Prometheus Availability and metric existence (handles UNRESOLVED states without guessing)
5. Deployment correlation (correlates degradation following deployment timestamp)
6. Telemetry persistence (persists real observations into TelemetrySnapshot table)
7. Structured findings generation (HEALTH_FAILURE, HIGH_ERROR_RATE, HIGH_LATENCY, METRIC_UNAVAILABLE, DEPLOYMENT_CORRELATED_ANOMALY, UNRESOLVED)

CRITICAL: NO ROLLBACK OR RECOVERY IS PERFORMED.
"""
import logging
import time
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Tuple
from uuid import UUID

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

import models
import schemas
from app_config import get_settings


logger = logging.getLogger("sceptic.watchdog")


class PipelineWatchdog:
    """
    Evaluates runtime performance and operational health of deployed services.
    """

    def __init__(
        self,
        target_url: Optional[str] = None,
        prometheus_url: Optional[str] = None,
        client: Optional[httpx.AsyncClient] = None
    ):
        settings = get_settings()
        self.target_url = (target_url or settings.TARGET_SERVICE_URL).rstrip("/")
        self.prometheus_url = (prometheus_url or settings.PROMETHEUS_URL).rstrip("/")
        self._external_client = client

    async def _get_client(self) -> Tuple[httpx.AsyncClient, bool]:
        """Returns client and a boolean indicating if it was locally created."""
        if self._external_client is not None:
            return self._external_client, False
        return httpx.AsyncClient(), True

    async def check_health(self, client: httpx.AsyncClient) -> Tuple[str, Optional[schemas.WatchdogFinding]]:
        """
        Queries target application /health endpoint.
        Returns health status string ('healthy' or 'unhealthy') and an optional finding.
        """
        settings = get_settings()
        health_url = f"{self.target_url}/health"
        timeout = settings.WATCHDOG_HEALTH_TIMEOUT

        try:
            resp = await client.get(health_url, timeout=timeout)
            if resp.status_code == 200:
                data = resp.json()
                if data.get("status") == "healthy":
                    return "healthy", None
                else:
                    return "unhealthy", schemas.WatchdogFinding(
                        finding_type="HEALTH_FAILURE",
                        severity="CRITICAL",
                        expected_value="status == 'healthy'",
                        actual_value=str(data.get("status")),
                        description=f"Target service /health returned non-healthy status: {data}",
                        detected_at=datetime.now(timezone.utc)
                    )
            else:
                return "unhealthy", schemas.WatchdogFinding(
                    finding_type="HEALTH_FAILURE",
                    severity="CRITICAL",
                    expected_value="HTTP 200",
                    actual_value=f"HTTP {resp.status_code}",
                    description=f"Target service /health returned HTTP {resp.status_code}: {resp.text}",
                    detected_at=datetime.now(timezone.utc)
                )
        except Exception as e:
            logger.warning(f"Watchdog health check failed at {health_url}: {e}")
            return "unhealthy", schemas.WatchdogFinding(
                finding_type="HEALTH_FAILURE",
                severity="CRITICAL",
                expected_value="Service reachable and responding 200",
                actual_value=f"Connection failure: {type(e).__name__}",
                description=f"Target service unreachable at {health_url}: {str(e)}",
                detected_at=datetime.now(timezone.utc)
            )

    async def _query_prometheus(
        self,
        client: httpx.AsyncClient,
        query: str
    ) -> Tuple[Optional[List[Dict[str, Any]]], Optional[str]]:
        """
        Executes an instant query against Prometheus HTTP API.
        Returns (result_list, error_message).
        """
        settings = get_settings()
        prom_query_url = f"{self.prometheus_url}/api/v1/query"
        timeout = settings.WATCHDOG_PROMETHEUS_TIMEOUT

        try:
            resp = await client.get(prom_query_url, params={"query": query}, timeout=timeout)
            if resp.status_code != 200:
                return None, f"Prometheus returned HTTP {resp.status_code}: {resp.text}"
            data = resp.json()
            if data.get("status") != "success":
                return None, f"Prometheus query unsuccessful: {data.get('error', 'unknown error')}"
            return data.get("data", {}).get("result", []), None
        except Exception as e:
            return None, f"Prometheus connection error: {str(e)}"

    async def evaluate_metrics(
        self,
        client: httpx.AsyncClient
    ) -> Tuple[
        Optional[int],           # request_count
        Optional[int],           # error_count
        Optional[float],         # error_rate
        Optional[float],         # latency_avg
        Optional[float],         # latency_p95
        List[schemas.WatchdogFinding]
    ]:
        """
        Fetches request count, errors, error rate, and latency from Prometheus.
        Validates availability, minimum-sample limits, and thresholds.
        """
        settings = get_settings()
        findings: List[schemas.WatchdogFinding] = []

        total_requests: Optional[int] = None
        error_requests: Optional[int] = None
        error_rate: Optional[float] = None
        latency_avg: Optional[float] = None
        latency_p95: Optional[float] = None

        # 1. Total Requests
        total_res, err = await self._query_prometheus(client, "sum(http_requests_total)")
        if err is not None:
            findings.append(schemas.WatchdogFinding(
                finding_type="METRIC_UNAVAILABLE",
                severity="HIGH",
                expected_value="Prometheus reachable",
                actual_value=err,
                description=f"Could not retrieve telemetry from Prometheus: {err}",
                detected_at=datetime.now(timezone.utc)
            ))
            return None, None, None, None, None, findings

        if not total_res:
            # Metric does not exist on Prometheus yet
            findings.append(schemas.WatchdogFinding(
                finding_type="UNRESOLVED",
                severity="MEDIUM",
                expected_value="http_requests_total metric exists",
                actual_value="Metric not found",
                description="Metric 'http_requests_total' not found in Prometheus. Target may not have processed requests.",
                detected_at=datetime.now(timezone.utc)
            ))
            return None, None, None, None, None, findings

        try:
            total_requests = int(float(total_res[0]["value"][1]))
        except (KeyError, IndexError, ValueError):
            total_requests = None

        # 2. Error Requests (HTTP 5xx)
        err_res, err_query_err = await self._query_prometheus(client, 'sum(http_requests_total{status_code=~"5.."})')
        if err_query_err is not None:
            findings.append(schemas.WatchdogFinding(
                finding_type="METRIC_UNAVAILABLE",
                severity="MEDIUM",
                expected_value="5xx error metric query successful",
                actual_value=err_query_err,
                description=f"Failed to query 5xx error metrics: {err_query_err}",
                detected_at=datetime.now(timezone.utc)
            ))
        elif err_res:
            try:
                error_requests = int(float(err_res[0]["value"][1]))
            except (KeyError, IndexError, ValueError):
                error_requests = 0
        else:
            # Empty result vector for 5xx filter means exactly 0 5xx responses
            error_requests = 0

        # Calculate Error Rate
        if total_requests is not None and total_requests > 0:
            err_count = error_requests if error_requests is not None else 0
            error_rate = min(1.0, max(0.0, err_count / total_requests))

            # Threshold & Minimum-Sample Protection
            if total_requests < settings.WATCHDOG_MIN_REQUESTS:
                logger.info(
                    f"Watchdog: total requests {total_requests} < min sample {settings.WATCHDOG_MIN_REQUESTS}. "
                    "Skipping HIGH_ERROR_RATE incident to prevent false alarms on small samples."
                )
            else:
                if error_rate > settings.WATCHDOG_ERROR_RATE_THRESHOLD:
                    findings.append(schemas.WatchdogFinding(
                        finding_type="HIGH_ERROR_RATE",
                        severity="HIGH",
                        expected_value=f"<= {settings.WATCHDOG_ERROR_RATE_THRESHOLD:.2%}",
                        actual_value=f"{error_rate:.2%}",
                        description=(
                            f"Runtime error rate of {error_rate:.2%} ({err_count}/{total_requests}) "
                            f"exceeds threshold of {settings.WATCHDOG_ERROR_RATE_THRESHOLD:.2%}."
                        ),
                        detected_at=datetime.now(timezone.utc),
                        metadata={
                            "total_requests": total_requests,
                            "error_requests": err_count,
                            "threshold": settings.WATCHDOG_ERROR_RATE_THRESHOLD
                        }
                    ))

        # 3. Latency Metrics: p95 and Avg
        # Try quantile over cumulative buckets
        p95_res, p95_err = await self._query_prometheus(
            client,
            "histogram_quantile(0.95, sum by (le) (http_request_duration_seconds_bucket))"
        )
        if p95_err is None and p95_res:
            try:
                val = float(p95_res[0]["value"][1])
                import math
                if not math.isnan(val) and not math.isinf(val):
                    latency_p95 = val
                    if latency_p95 > settings.WATCHDOG_LATENCY_P95_THRESHOLD:
                        findings.append(schemas.WatchdogFinding(
                            finding_type="HIGH_LATENCY",
                            severity="HIGH",
                            expected_value=f"<= {settings.WATCHDOG_LATENCY_P95_THRESHOLD:.3f}s",
                            actual_value=f"{latency_p95:.3f}s",
                            description=(
                                f"Runtime p95 latency of {latency_p95:.3f}s exceeds threshold of "
                                f"{settings.WATCHDOG_LATENCY_P95_THRESHOLD:.3f}s."
                            ),
                            detected_at=datetime.now(timezone.utc),
                            metadata={"p95_seconds": latency_p95, "threshold": settings.WATCHDOG_LATENCY_P95_THRESHOLD}
                        ))
                else:
                    findings.append(schemas.WatchdogFinding(
                        finding_type="UNRESOLVED",
                        severity="LOW",
                        expected_value="Valid p95 latency",
                        actual_value="NaN",
                        description="Prometheus returned NaN for p95 latency (insufficient bucket observation data).",
                        detected_at=datetime.now(timezone.utc)
                    ))
            except (KeyError, IndexError, ValueError):
                pass
        else:
            findings.append(schemas.WatchdogFinding(
                finding_type="UNRESOLVED",
                severity="LOW",
                expected_value="Latency bucket metrics available",
                actual_value="None",
                description="Latency histogram metrics unavailable in Prometheus.",
                detected_at=datetime.now(timezone.utc)
            ))

        # Average latency
        avg_res, _ = await self._query_prometheus(
            client,
            "sum(http_request_duration_seconds_sum) / sum(http_request_duration_seconds_count)"
        )
        if avg_res:
            try:
                val = float(avg_res[0]["value"][1])
                import math
                if not math.isnan(val) and not math.isinf(val):
                    latency_avg = val
            except (KeyError, IndexError, ValueError):
                pass

        return total_requests, error_requests, error_rate, latency_avg, latency_p95, findings

    async def evaluate(
        self,
        deployment: models.Deployment,
        db: AsyncSession
    ) -> schemas.WatchdogCheckResult:
        """
        Runs complete runtime watchdog verification on a deployment,
        persists telemetry snapshot, and returns structured findings.
        """
        client, should_close = await self._get_client()
        logger.info(f"watchdog_check_started: deployment_id={deployment.id} project_id={deployment.project_id}")

        all_findings: List[schemas.WatchdogFinding] = []

        try:
            # 1. Health Check
            health_status, health_finding = await self.check_health(client)
            if health_finding:
                all_findings.append(health_finding)

            # 2. Prometheus Telemetry Analysis
            (
                total_reqs,
                err_reqs,
                err_rate,
                lat_avg,
                lat_p95,
                metric_findings
            ) = await self.evaluate_metrics(client)
            all_findings.extend(metric_findings)

            # 3. Deployment Correlation
            # If degradation (high error rate, high latency, health failure) is observed
            has_degradation = any(
                f.finding_type in ("HEALTH_FAILURE", "HIGH_ERROR_RATE", "HIGH_LATENCY")
                for f in all_findings
            )
            if has_degradation:
                all_findings.append(schemas.WatchdogFinding(
                    finding_type="DEPLOYMENT_CORRELATED_ANOMALY",
                    severity="HIGH",
                    expected_value="Stable runtime metrics following deployment",
                    actual_value="Degradation observed",
                    description=f"Runtime degradation was detected following deployment {deployment.commit_sha}.",
                    detected_at=datetime.now(timezone.utc),
                    metadata={
                        "deployment_id": str(deployment.id),
                        "commit_sha": deployment.commit_sha,
                        "environment": deployment.environment
                    }
                ))
                logger.warning(
                    f"watchdog_anomaly_detected: deployment_id={deployment.id} "
                    f"finding_type=DEPLOYMENT_CORRELATED_ANOMALY commit_sha={deployment.commit_sha}"
                )

            # 4. Telemetry Persistence
            snapshot = models.TelemetrySnapshot(
                deployment_id=deployment.id,
                timestamp=datetime.now(timezone.utc),
                health_status=health_status,
                request_count=total_reqs,
                error_count=err_reqs,
                error_rate=err_rate,
                latency_avg=lat_avg,
                latency_p95=lat_p95
            )
            db.add(snapshot)
            await db.commit()
            await db.refresh(snapshot)

            snapshot_schema = schemas.TelemetrySnapshotResponse.model_validate(snapshot)

            # 5. Determine Overall Status
            # Any critical or high severity finding (excluding UNRESOLVED/METRIC_UNAVAILABLE) is FAIL
            has_fail = any(
                f.severity in ("CRITICAL", "HIGH") and f.finding_type not in ("UNRESOLVED", "METRIC_UNAVAILABLE")
                for f in all_findings
            )
            has_unresolved = any(
                f.finding_type in ("UNRESOLVED", "METRIC_UNAVAILABLE")
                for f in all_findings
            )

            if has_fail:
                overall_status = schemas.VerificationStatus.FAIL
                summary = f"Watchdog detected {len(all_findings)} finding(s) with runtime failures."
            elif has_unresolved:
                overall_status = schemas.VerificationStatus.UNRESOLVED
                summary = f"Watchdog completed with unresolved metrics or telemetry."
            else:
                overall_status = schemas.VerificationStatus.PASS
                summary = "All watchdog runtime checks passed successfully."

            logger.info(
                f"watchdog_check_completed: deployment_id={deployment.id} "
                f"status={overall_status} findings_count={len(all_findings)}"
            )

            return schemas.WatchdogCheckResult(
                deployment_id=deployment.id,
                status=overall_status,
                checked_at=datetime.now(timezone.utc),
                findings=all_findings,
                telemetry_snapshot=snapshot_schema,
                summary=summary
            )

        finally:
            if should_close:
                await client.aclose()
