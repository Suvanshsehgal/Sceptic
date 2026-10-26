import os
import sys
import logging
from typing import Callable, Dict, Any, List, Optional

# Ensure worker directory is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

from blind_tester import SpecificationMetadata
from crewai_wrapper import run_fact_checker
from crewai_blind_tester import run_blind_tester
from crewai_security_guard import run_security_guard
from synthesizer import ReportSynthesizer

logger = logging.getLogger("sceptic.orchestrator")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

class AuditOrchestrator:
    """
    Fan-out / Fan-in CrewAI Orchestrator.

    Architecture:
    Audit Request
         │
    ┌────┴─────────────────────────────┐
    ▼                                  ▼                                  ▼
    Fact-Checker Agent       Blind-Tester Agent (ISOLATED)     Security-Guard Agent
    (AST/dir/inspect)        (Docstring/Spec ONLY)             (Semgrep/Bandit/Groq)
    │                                  │                                  │
    └──────────────────────────────────┼──────────────────────────────────┘
                                       ▼
                              Report Synthesizer
                                       ▼
                          Trust Score & Final Report

    Fact-Checker and Security-Guard look at the whole file, so they run once per file (run_file_checks).
    Blind-Tester works on one function specification at a time (run_spec_checks).
    """
    def __init__(self):
        self.synthesizer = ReportSynthesizer()

    @staticmethod
    def _notify(progress_callback: Optional[Callable], agent_name: str, findings: List[Dict[str, Any]]) -> None:
        if progress_callback is not None:
            try:
                progress_callback(agent_name, len(findings))
            except Exception as e:  # progress is informational and must never fail the audit
                logger.warning(f"Progress callback failed for {agent_name}: {e}")

    def run_file_checks(
        self,
        source_code: str,
        file_path: str = "target.py",
        language: str = "python",
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Runs the agents that analyse the whole file: Fact-Checker and Security-Guard."""
        # 1. Fact-Checker (Language-Agnostic Deterministic Verification)
        fact_checker_findings: List[Dict[str, Any]] = []
        try:
            logger.info("Executing Fact-Checker Agent...")
            fact_checker_findings = run_fact_checker(
                source_code=source_code,
                file_path=file_path,
                language=language or "python"
            )
            logger.info(f"Fact-Checker completed with {len(fact_checker_findings)} findings.")
        except Exception as e:
            logger.error(f"Fact-Checker Agent failed: {str(e)}")
            fact_checker_findings.append({
                "agent_name": "Fact-Checker",
                "severity": "MEDIUM",
                "status": "ERROR",
                "title": "Fact-Checker Execution Error",
                "description": f"Fact-Checker agent encountered an error: {str(e)}",
                "file_path": file_path
            })

        self._notify(progress_callback, "Fact-Checker", fact_checker_findings)

        # 2. Security Guard (Semgrep & Bandit static analysis + Groq context)
        security_guard_findings: List[Dict[str, Any]] = []
        try:
            logger.info("Executing Security Guard Agent...")
            security_guard_findings = run_security_guard(
                source_code=source_code,
                file_path=file_path,
                run_llm_analysis=True
            )
            logger.info(f"Security Guard completed with {len(security_guard_findings)} findings.")
        except Exception as e:
            logger.error(f"Security Guard Agent failed: {str(e)}")
            security_guard_findings.append({
                "agent_name": "Security-Guard",
                "severity": "MEDIUM",
                "status": "ERROR",
                "title": "Security-Guard Execution Error",
                "description": f"Security Guard agent encountered an error: {str(e)}",
                "file_path": file_path
            })

        self._notify(progress_callback, "Security-Guard", security_guard_findings)

        return {"fact_checker": fact_checker_findings, "security_guard": security_guard_findings}

    def run_spec_checks(
        self,
        source_code: str,
        specification_metadata: SpecificationMetadata,
        file_path: str = "target.py",
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> List[Dict[str, Any]]:
        """Runs the Blind-Tester for one function specification."""
        logger.info(f"Starting blind test for function '{specification_metadata.function_name}' ({file_path})")

        # Blind Tester (Strict Information Isolation)
        blind_tester_findings: List[Dict[str, Any]] = []
        try:
            logger.info("Executing Blind Tester Agent (Information-Isolated)...")
            # Enforce that no source code or other findings leak into specification
            specification_metadata.validate_isolation()

            # Target implementation is provided strictly to execution environment, NOT LLM context
            blind_tester_findings = run_blind_tester(
                function_name=specification_metadata.function_name,
                docstring=specification_metadata.docstring,
                specification=specification_metadata.specification,
                implementation_code=source_code,
                module_name=specification_metadata.module_name,
                language=getattr(specification_metadata, "language", "python") or "python",
            )
            logger.info(f"Blind Tester completed with {len(blind_tester_findings)} findings.")
        except Exception as e:
            logger.error(f"Blind Tester Agent failed: {str(e)}")
            blind_tester_findings.append({
                "agent_name": "Blind-Tester",
                "severity": "MEDIUM",
                "status": "ERROR",
                "title": "Blind-Tester Execution Error",
                "description": f"Blind Tester agent encountered an error: {str(e)}",
                "file_path": file_path
            })

        # The Blind-Tester only knows the module name, so it labels findings with a .py path. Use the audited file instead.
        for finding in blind_tester_findings:
            finding["file_path"] = file_path

        self._notify(progress_callback, "Blind-Tester", blind_tester_findings)

        return blind_tester_findings

    def run_pipeline(
        self,
        source_code: str,
        specification_metadata: SpecificationMetadata,
        file_path: str = "target.py",
        progress_callback: Optional[Callable[[str, int], None]] = None,
    ) -> Dict[str, Any]:
        """
        Runs the fan-out agents for a single specification and the synthesizer.
        progress_callback(agent_name, finding_count) is called as each agent finishes, so the worker can stream progress.
        """
        language = getattr(specification_metadata, "language", "python") or "python"
        file_findings = self.run_file_checks(source_code, file_path, language, progress_callback)
        spec_findings = self.run_spec_checks(source_code, specification_metadata, file_path, progress_callback)

        # ========================================================
        # FAN-IN TO REPORT SYNTHESIZER
        # ========================================================
        logger.info("Executing Report Synthesizer (Fan-in)...")
        report = self.synthesizer.synthesize(
            fact_checker_findings=file_findings["fact_checker"],
            blind_tester_findings=spec_findings,
            security_guard_findings=file_findings["security_guard"],
        )
        logger.info(f"Synthesis complete: Trust Score {report['trust_score']}/100, Recommendation: {report['recommendation']}")

        return report
