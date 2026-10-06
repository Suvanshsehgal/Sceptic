import json
from typing import List, Dict, Any, Optional

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

    @classmethod
    def calculate(cls, findings: List[Dict[str, Any]]) -> Dict[str, Any]:
        score = 100
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
            
            if status == "UNRESOLVED":
                severity_breakdown["UNRESOLVED"] += 1
                penalty = cls.WEIGHTS["UNRESOLVED"]
                score -= penalty
                deductions_detail.append(f"UNRESOLVED finding '{f.get('title', '')}': -{penalty} pts")
            elif sev in severity_breakdown:
                severity_breakdown[sev] += 1
                penalty = cls.WEIGHTS.get(sev, 0)
                if penalty > 0:
                    score -= penalty
                    deductions_detail.append(f"{sev} finding '{f.get('title', '')}': -{penalty} pts")

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
    Synthesizes findings from Fact-Checker, Blind-Tester, and Security-Guard
    into a structured, executive audit report.
    """
    def synthesize(
        self,
        fact_checker_findings: List[Dict[str, Any]],
        blind_tester_findings: List[Dict[str, Any]],
        security_guard_findings: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        all_findings = []
        all_findings.extend(fact_checker_findings)
        all_findings.extend(blind_tester_findings)
        all_findings.extend(security_guard_findings)

        trust_info = TrustScoreCalculator.calculate(all_findings)
        trust_score = trust_info["trust_score"]
        recommendation = trust_info["recommendation"]
        severity_breakdown = trust_info["severity_breakdown"]

        # Calculate agent contributions
        agent_contributions = {
            "Fact-Checker": len(fact_checker_findings),
            "Blind-Tester": len(blind_tester_findings),
            "Security-Guard": len(security_guard_findings)
        }

        # Synthesize executive summary
        summary_lines = [
            f"Audit completed with Trust Score: {trust_score}/100 ({recommendation}).",
            f"Total findings: {len(all_findings)} (Critical: {severity_breakdown['CRITICAL']}, High: {severity_breakdown['HIGH']}, Medium: {severity_breakdown['MEDIUM']}, Low: {severity_breakdown['LOW']}).",
            f"Agent contributions: Fact-Checker ({agent_contributions['Fact-Checker']}), Blind-Tester ({agent_contributions['Blind-Tester']}), Security-Guard ({agent_contributions['Security-Guard']})."
        ]

        if recommendation == "APPROVE":
            summary_lines.append("Code meets specification contracts and static security policies.")
        elif recommendation == "REQUEST_CHANGES":
            summary_lines.append("Code has minor discrepancies or security warnings that should be addressed before merging.")
        else:
            summary_lines.append("Critical vulnerabilities or specification violations detected. Code blocked.")

        executive_summary = "\n".join(summary_lines)

        return {
            "trust_score": trust_score,
            "recommendation": recommendation,
            "summary": executive_summary,
            "severity_breakdown": severity_breakdown,
            "agent_contributions": agent_contributions,
            "total_findings": len(all_findings),
            "all_findings": all_findings
        }
