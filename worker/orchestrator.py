import os
import sys
import logging
from typing import Dict, Any, List, Optional

# Ensure worker directory is on sys.path
sys.path.insert(0, os.path.dirname(__file__))

from fact_checker import analyze_code
from blind_tester import SpecificationMetadata, run_blind_test
from security_guard import run_security_scan
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
    """
    def __init__(self):
        self.synthesizer = ReportSynthesizer()

    def run_pipeline(
        self,
        source_code: str,
        specification_metadata: SpecificationMetadata,
        file_path: str = "target.py"
    ) -> Dict[str, Any]:
        logger.info(f"Starting audit pipeline for function '{specification_metadata.function_name}' ({file_path})")

        # ========================================================
        # STEP 1: FAN-OUT TO INDEPENDENT AGENTS
        # ========================================================
        
        # 1. Fact-Checker (AST API Inspection)
        fact_checker_findings: List[Dict[str, Any]] = []
        try:
            logger.info("Executing Fact-Checker Agent...")
            fact_checker_findings = analyze_code(source_code)
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

        # 2. Blind Tester (Strict Information Isolation)
        blind_tester_findings: List[Dict[str, Any]] = []
        try:
            logger.info("Executing Blind Tester Agent (Information-Isolated)...")
            # Enforce that no source code or other findings leak into specification
            specification_metadata.validate_isolation()
            
            # Target implementation is provided strictly to execution environment, NOT LLM context
            blind_tester_findings = run_blind_test(
                spec=specification_metadata,
                implementation_code=source_code,
                file_path=file_path
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

        # 3. Security Guard (Semgrep & Bandit static analysis + Groq context)
        security_guard_findings: List[Dict[str, Any]] = []
        try:
            logger.info("Executing Security Guard Agent...")
            security_guard_findings = run_security_scan(
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

        # ========================================================
        # STEP 2: FAN-IN TO REPORT SYNTHESIZER
        # ========================================================
        logger.info("Executing Report Synthesizer (Fan-in)...")
        report = self.synthesizer.synthesize(
            fact_checker_findings=fact_checker_findings,
            blind_tester_findings=blind_tester_findings,
            security_guard_findings=security_guard_findings
        )
        logger.info(f"Synthesis complete: Trust Score {report['trust_score']}/100, Recommendation: {report['recommendation']}")

        return report
