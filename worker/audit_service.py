import os
import ast
import sys
import logging
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

# Ensure root and worker directories are in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator import AuditOrchestrator
from blind_tester import SpecificationMetadata
from synthesizer import TrustScoreCalculator, ReportSynthesizer

from languages.detector import LanguageDetector, DEFAULT_IGNORED_DIRS, EXTENSION_MAP
from languages.universal_parser import UniversalParser
from languages.base import LanguageAdapterRegistry

logger = logging.getLogger("sceptic.service")

class AuditService:
    """
    Shared Audit Service layer.
    Reused identically by:
    - CLI (in-process synchronous execution)
    - Celery Worker (asynchronous background execution)
    - FastAPI Webhook
    
    Architecture:
    FastAPI ──────┐
                  │
    CLI ──────────┼──► Shared Audit Service ──► AuditOrchestrator ──► CrewAI Agents
                  │
    Celery ───────┘
    """
    def __init__(self):
        self.orchestrator = AuditOrchestrator()
        self.synthesizer = ReportSynthesizer()
        self.detector = LanguageDetector()

    def audit_path(
        self,
        target_path: str,
        progress_callback: Optional[Callable[[str, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Validates target path and executes the Sceptic audit pipeline in-process.
        Supports multi-language projects (Python, Java, JavaScript, TypeScript).
        Returns a structured audit report.
        """
        path_obj = Path(target_path).resolve()

        # 1. Path existence validation
        if not path_obj.exists():
            raise FileNotFoundError(f"Path does not exist: {target_path}")

        # 2. Path readability validation
        if not os.access(path_obj, os.R_OK):
            raise PermissionError(f"Path is not readable: {target_path}")

        # 3. Collect target files across supported languages
        target_files: List[Path] = []
        if path_obj.is_file():
            lang = self.detector.detect_file_language(str(path_obj))
            if not lang:
                raise ValueError(f"Unsupported file type: {path_obj.name}")
            target_files = [path_obj]
        elif path_obj.is_dir():
            for root, dirs, files in os.walk(path_obj):
                dirs[:] = [
                    d for d in dirs
                    if d not in DEFAULT_IGNORED_DIRS and not d.startswith(".")
                ]
                for file in files:
                    ext = Path(file).suffix.lower()
                    if ext in EXTENSION_MAP and not file.startswith("test_") and not file.endswith(".test.js") and not file.endswith(".test.ts"):
                        target_files.append(Path(root) / file)

            if not target_files:
                raise ValueError(f"No supported source files found in directory: {target_path}")
        else:
            raise ValueError(f"Unsupported path type: {target_path}")

        # Detect overall language distribution
        lang_stats = self.detector.detect_languages(target_path)

        if progress_callback:
            progress_callback("START", f"Discovered {len(target_files)} source file(s) across languages: {', '.join([l['name'] for l in lang_stats.get('languages', [])])}.")

        all_findings: List[Dict[str, Any]] = []
        scanned_files_list: List[str] = []
        agent_statuses = {
            "Fact-Checker": "OK",
            "Blind-Tester": "OK",
            "Security-Guard": "OK",
            "Synthesizer": "OK"
        }

        # 4. Audit each discovered file
        for src_file in target_files:
            rel_path = str(src_file.relative_to(path_obj.parent if path_obj.is_file() else path_obj))
            scanned_files_list.append(rel_path)
            file_lang = self.detector.detect_file_language(str(src_file)) or "python"
            adapter = LanguageAdapterRegistry.get_adapter(file_lang)
            test_fw = adapter.testing_framework if adapter else "pytest"

            try:
                with open(src_file, "r", encoding="utf-8") as f:
                    source_code = f.read()
            except Exception as e:
                logger.error(f"Failed to read file {src_file}: {e}")
                all_findings.append({
                    "agent_name": "Security-Guard",
                    "severity": "MEDIUM",
                    "status": "ERROR",
                    "title": "File Read Error",
                    "description": f"Could not read file {rel_path}: {str(e)}",
                    "file_path": rel_path
                })
                continue

            # Extract functions or module-level specs
            func_specs = self._extract_specifications(source_code, src_file.stem, language=file_lang, testing_framework=test_fw)

            for spec in func_specs:
                if progress_callback:
                    progress_callback("AGENT_START", f"Auditing '{spec.function_name}' in {rel_path}...")

                try:
                    report = self.orchestrator.run_pipeline(
                        source_code=source_code,
                        specification_metadata=spec,
                        file_path=rel_path
                    )
                    file_findings = report.get("all_findings", [])
                    all_findings.extend(file_findings)

                    # Update agent statuses if errors occurred
                    for finding in file_findings:
                        if finding.get("status") == "ERROR":
                            agent_name = finding.get("agent_name")
                            if agent_name in agent_statuses:
                                agent_statuses[agent_name] = "PARTIAL_FAILURE"

                except Exception as e:
                    logger.exception(f"Orchestration failure on {rel_path}: {e}")
                    agent_statuses["Synthesizer"] = "PARTIAL_FAILURE"
                    all_findings.append({
                        "agent_name": "Synthesizer",
                        "severity": "HIGH",
                        "status": "ERROR",
                        "title": "Audit Pipeline Failure",
                        "description": f"Audit execution failed on {rel_path}: {str(e)}",
                        "file_path": rel_path
                    })

        # 5. Final Synthesis across all inspected files
        if progress_callback:
            progress_callback("SYNTHESIZER", "Synthesizing final Trust Score and audit report...")

        trust_info = TrustScoreCalculator.calculate(all_findings)
        trust_score = trust_info["trust_score"]
        recommendation = trust_info["recommendation"]
        severity_breakdown = trust_info["severity_breakdown"]

        # Aggregate contributions
        agent_contributions = {
            "Fact-Checker": len([f for f in all_findings if f.get("agent_name") == "Fact-Checker"]),
            "Blind-Tester": len([f for f in all_findings if f.get("agent_name") == "Blind-Tester"]),
            "Security-Guard": len([f for f in all_findings if f.get("agent_name") == "Security-Guard"])
        }

        summary_text = (
            f"Audit completed across {len(scanned_files_list)} file(s). "
            f"Trust Score: {trust_score}/100 ({recommendation}). "
            f"Total findings: {len(all_findings)}."
        )

        return {
            "target_path": str(path_obj),
            "files_scanned": scanned_files_list,
            "trust_score": trust_score,
            "recommendation": recommendation,
            "summary": summary_text,
            "severity_breakdown": severity_breakdown,
            "agent_contributions": agent_contributions,
            "agent_statuses": agent_statuses,
            "findings": all_findings,
            "total_findings": len(all_findings)
        }

    def _extract_specifications(
        self,
        source_code: str,
        module_name: str,
        language: str = "python",
        testing_framework: str = "pytest"
    ) -> List[SpecificationMetadata]:
        """
        Parses source code to identify functions and docstrings across languages.
        If no functions exist, generates an entrypoint specification.
        """
        specs: List[SpecificationMetadata] = []
        try:
            parsed = UniversalParser.parse(source_code, language, file_path=f"{module_name}.{language}")
            for fn in parsed.functions:
                if not fn.name.startswith("_") and fn.name not in ("anonymous", ""):
                    doc = fn.docstring or f"Function '{fn.name}'."
                    spec_text = f"Function '{fn.name}' specification in {language}."
                    specs.append(SpecificationMetadata(
                        function_name=fn.name,
                        docstring=doc,
                        specification=spec_text,
                        module_name=module_name,
                        language=language,
                        testing_framework=testing_framework
                    ))
        except Exception:
            pass

        # Fallback if no functions were discovered
        if not specs:
            specs.append(SpecificationMetadata(
                function_name=f"{module_name}_entry",
                docstring=f"{language.capitalize()} module execution inspection.",
                specification="Verify safe and correct execution.",
                module_name=module_name,
                language=language,
                testing_framework=testing_framework
            ))

        return specs
