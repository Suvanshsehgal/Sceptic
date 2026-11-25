import json
import os
import sys
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence

sys.path.insert(0, os.path.dirname(__file__))
from audit_models import AuditContext, AuditReport, VERIFICATION_AGENTS

class TrustScoreCalculator:
    """
    Transparent and deterministic Trust Score calculation.
    
    Methodology:
    - Base score: 100 points
    - Deductions per verified finding based on severity:
        - CRITICAL: -35 points (High severity security exploits, RCE)
        - HIGH:     -20 points (Missing required APIs, specification test failures, severe security issues)
        - MEDIUM:   -10 points (Invalid parameters, moderate security warnings)
        - LOW:      -3 points  (Minor warnings or stylistic/informational security notices)
        - UNRESOLVED / ERROR: -5 points (Uncertainty penalty for dynamically unresolved or failed components)
    - Scale is clamped to [0, 100].
    
    Interpretation Bands:
    - 85 - 100: HIGH TRUST ("APPROVE")
    - 65 - 84:  MODERATE TRUST ("REQUEST_CHANGES")
    - 0  - 64:  LOW TRUST / UNTRUSTED ("BLOCK")
    """
    WEIGHTS = {
        "CRITICAL": 35,
        "HIGH": 20,
        "MEDIUM": 10,
        "LOW": 3,
        "UNRESOLVED": 5,
        "ERROR": 5
    }
    # "Could not check" findings (unresolved calls, missing tools, unreachable databases, import errors in generated
    # tests) are reported, but they share one capped penalty so they cannot outweigh real defects.
    UNCERTAINTY_CAP = 15

    @classmethod
    def calculate(cls, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        score = 100
        uncertainty_penalty = 0
        severity_breakdown = {
            "CRITICAL": 0,
            "HIGH": 0,
            "MEDIUM": 0,
            "LOW": 0,
            "INFO": 0,
            "UNRESOLVED": 0
        }
        deductions_detail = []

        for f in findings:
            sev = (f.get("severity") or "INFO").upper()
            status = (f.get("status") or "").upper()

            if status in ("UNRESOLVED", "ERROR"):
                severity_breakdown["UNRESOLVED"] += 1
                uncertainty_penalty += cls.WEIGHTS["UNRESOLVED"]
                deductions_detail.append(f"Not fully checked: '{f.get('title', '')}'")
            elif sev in severity_breakdown:
                severity_breakdown[sev] += 1
                penalty = cls.WEIGHTS.get(sev, 0)
                if penalty > 0:
                    score -= penalty
                    deductions_detail.append(f"{sev} finding '{f.get('title', '')}': -{penalty} pts")

        applied_uncertainty = min(uncertainty_penalty, cls.UNCERTAINTY_CAP)
        if applied_uncertainty:
            score -= applied_uncertainty
            deductions_detail.append(f"Uncertainty penalty (capped): -{applied_uncertainty} pts")

        score = max(0, min(100, score))

        if score >= 85:
            recommendation = "APPROVE"
        elif score >= 65:
            recommendation = "REQUEST_CHANGES"
        else:
            recommendation = "BLOCK"

        return {
            "trust_score": score,
            "recommendation": recommendation,
            "severity_breakdown": severity_breakdown,
            "deductions_detail": deductions_detail
        }


class ReportSynthesizer:
    """
    Fan-in: reads every agent's findings from the shared AuditContext and builds the structured AuditReport.
    The score and verdict come only from TrustScoreCalculator. No LLM is involved here.
    """
    @staticmethod
    def _default_summary(trust_info: Dict[str, Any], contributions: Dict[str, int], total_findings: int) -> str:
        return (
            f"Trust Score: {trust_info['trust_score']}/100 ({trust_info['recommendation']}). "
            f"Total findings: {total_findings}."
        )

    def build_report(
        self,
        ctx: AuditContext,
        agents: Sequence[str] = VERIFICATION_AGENTS,
        summary_fn: Optional[Callable[[Dict[str, Any], Dict[str, int], int], str]] = None,
    ) -> AuditReport:
        with ctx._lock:
            findings = list(ctx.all_findings)
            outputs = {name: len(items) for name, items in ctx.agent_outputs.items()}
            statuses = dict(ctx.agent_statuses)
            events = list(ctx.events)
            incomplete = list(ctx.incomplete_reasons)

        trust_info = TrustScoreCalculator.calculate(findings)
        if incomplete and trust_info["recommendation"] == "APPROVE":
            # Part of the code was never audited. An unchecked file must not be approved, whatever the score says.
            trust_info["recommendation"] = "REQUEST_CHANGES"
            trust_info["deductions_detail"].append(
                f"Audit incomplete ({len(incomplete)} failure(s)): APPROVE withheld."
            )
        contributions = {name: outputs.get(name, 0) for name in agents}
        summary = (summary_fn or self._default_summary)(trust_info, contributions, len(findings))
        duration = (datetime.now(timezone.utc) - ctx.started_at).total_seconds()

        return AuditReport(
            audit_id=ctx.audit_id,
            trace_id=ctx.trace_id,
            target_path=ctx.target_path,
            files_scanned=list(ctx.files_scanned),
            trust_score=trust_info["trust_score"],
            recommendation=trust_info["recommendation"],
            summary=summary,
            severity_breakdown=trust_info["severity_breakdown"],
            agent_contributions=contributions,
            agent_statuses=statuses,
            deductions_detail=trust_info["deductions_detail"],
            incomplete_reasons=incomplete,
            findings=findings,
            total_findings=len(findings),
            duration_seconds=round(duration, 3),
            execution_log=events,
        )

    @staticmethod
    def _three_agent_summary(trust_info: Dict[str, Any], contributions: Dict[str, int], total_findings: int) -> str:
        breakdown = trust_info["severity_breakdown"]
        recommendation = trust_info["recommendation"]
        lines = [
            f"Audit completed with Trust Score: {trust_info['trust_score']}/100 ({recommendation}).",
            f"Total findings: {total_findings} (Critical: {breakdown['CRITICAL']}, High: {breakdown['HIGH']}, Medium: {breakdown['MEDIUM']}, Low: {breakdown['LOW']}).",
            f"Agent contributions: Fact-Checker ({contributions['Fact-Checker']}), Blind-Tester ({contributions['Blind-Tester']}), Security-Guard ({contributions['Security-Guard']}).",
        ]
        if recommendation == "APPROVE":
            lines.append("Code meets specification contracts and static security policies.")
        elif recommendation == "REQUEST_CHANGES":
            lines.append("Code has minor discrepancies or security warnings that should be addressed before merging.")
        else:
            lines.append("Critical vulnerabilities or specification violations detected. Code blocked.")
        return "\n".join(lines)

    def synthesize(
        self,
        fact_checker_findings: List[Dict[str, Any]],
        blind_tester_findings: List[Dict[str, Any]],
        security_guard_findings: List[Dict[str, Any]],
        ctx: Optional[AuditContext] = None,
    ) -> Dict[str, Any]:
        """
        Three-agent synthesis used by the single-function pipeline. Returns the AuditReport as a dict.
        Pass the shared context to keep its execution log; otherwise a new one is created.
        """
        if ctx is None:
            ctx = AuditContext()
            ctx.record(fact_checker_findings, "Fact-Checker")
            ctx.record(blind_tester_findings, "Blind-Tester")
            ctx.record(security_guard_findings, "Security-Guard")
        report = self.build_report(
            ctx,
            agents=("Fact-Checker", "Blind-Tester", "Security-Guard"),
            summary_fn=self._three_agent_summary,
        )
        return report.to_dict()
