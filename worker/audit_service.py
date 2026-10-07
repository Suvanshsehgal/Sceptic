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

    def audit_path(
        self,
        target_path: str,
        progress_callback: Optional[Callable[[str, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Validates target path and executes the Sceptic audit pipeline in-process.
        Returns a structured audit report.
        """
        path_obj = Path(target_path).resolve()

        # 1. Path existence validation
        if not path_obj.exists():
            raise FileNotFoundError(f"Path does not exist: {target_path}")

        # 2. Path readability validation
        if not os.access(path_obj, os.R_OK):
            raise PermissionError(f"Path is not readable: {target_path}")

        # 3. Collect target Python files
        python_files: List[Path] = []
        if path_obj.is_file():
            if path_obj.suffix != ".py":
                raise ValueError(f"Target file must be a Python source file (.py): {path_obj.name}")
            python_files = [path_obj]
        elif path_obj.is_dir():
            # Exclude virtual environments, git, and cache directories
            excluded_dirs = {
                ".git", "__pycache__", ".pytest_cache", ".venv", "venv", "env",
                "node_modules", "dist", "build", ".mypy_cache"
            }
            for root, dirs, files in os.walk(path_obj):
                # Filter out excluded directories in-place
                dirs[:] = [d for d in dirs if d not in excluded_dirs and not d.startswith(".")]
                for file in files:
                    if file.endswith(".py") and not file.startswith("test_"):
                        python_files.append(Path(root) / file)

            if not python_files:
                raise ValueError(f"No Python source files found in directory: {target_path}")
        else:
            raise ValueError(f"Unsupported path type: {target_path}")

        if progress_callback:
            progress_callback("START", f"Discovered {len(python_files)} Python file(s) for audit.")

        all_findings: List[Dict[str, Any]] = []
        scanned_files_list: List[str] = []
        agent_statuses = {
            "Fact-Checker": "OK",
            "Blind-Tester": "OK",
            "Security-Guard": "OK",
            "Synthesizer": "OK"
        }

        # 4. Audit each discovered file
        for py_file in python_files:
            rel_path = str(py_file.relative_to(path_obj.parent if path_obj.is_file() else path_obj))
            scanned_files_list.append(rel_path)

            try:
                with open(py_file, "r", encoding="utf-8") as f:
                    source_code = f.read()
            except Exception as e:
                logger.error(f"Failed to read file {py_file}: {e}")
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
            func_specs = self._extract_specifications(source_code, py_file.stem)

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

    def _extract_specifications(self, source_code: str, module_name: str) -> List[SpecificationMetadata]:
        """
        Parses source code AST to identify top-level functions and docstrings.
        If no functions exist, generates a module-level specification.
        """
        specs: List[SpecificationMetadata] = []
        try:
            tree = ast.parse(source_code)
            for node in tree.body:
                if isinstance(node, ast.FunctionDef) and not node.name.startswith("_"):
                    docstring = ast.get_docstring(node) or "No docstring provided."
                    spec_text = f"Function '{node.name}' specification derived from docstring."
                    specs.append(SpecificationMetadata(
                        function_name=node.name,
                        docstring=docstring,
                        specification=spec_text,
                        module_name=module_name
                    ))
        except Exception:
            pass

        # Fallback if no functions were discovered
        if not specs:
            specs.append(SpecificationMetadata(
                function_name=f"{module_name}_entry",
                docstring="Module execution inspection.",
                specification="Verify safe and correct execution.",
                module_name=module_name
            ))

        return specs
