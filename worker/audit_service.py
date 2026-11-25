import os
import ast
import sys
import logging
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Dict, Any, List, Optional, Callable

# Ensure root and worker directories are in sys.path
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from orchestrator import AuditOrchestrator
from crewai_extra_agents import run_leak_hunter, run_purana_saman, run_jhooti_docstring
from blind_tester import SpecificationMetadata
from synthesizer import TrustScoreCalculator, ReportSynthesizer
from audit_models import AuditContext, AuditReport, VERIFICATION_AGENTS
import tracing

from languages.detector import LanguageDetector, DEFAULT_IGNORED_DIRS, EXTENSION_MAP
from languages.universal_parser import UniversalParser
from languages.base import LanguageAdapterRegistry

logger = logging.getLogger("sceptic.service")

# Blind-Tester specs of one file that run at the same time (each one is an LLM call plus a sandbox run).
# Defaults to 1: on a Docker Desktop host, concurrent sandbox containers slowed each spec about 5x.
SPEC_WORKERS = max(1, int(os.getenv("SCEPTIC_SPEC_WORKERS", "1")))

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
        Runs the audit and returns the report as a dict (the form the CLI, Celery task and API consume).
        Use audit_report() to get the validated AuditReport model.
        """
        return self.audit_report(target_path, progress_callback).to_dict()

    def audit_report(
        self,
        target_path: str,
        progress_callback: Optional[Callable[[str, str], None]] = None
    ) -> AuditReport:
        """
        Validates target path and executes the Sceptic audit pipeline in-process.
        Supports multi-language projects (Python, Java, JavaScript, TypeScript).
        Every agent writes its findings into one shared AuditContext; the Synthesizer builds the AuditReport from it.
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

        tracing.instrument_frameworks(("crewai", "google_adk"))
        ctx = AuditContext(target_path=str(path_obj))
        with tracing.trace(
            "sceptic.audit",
            input={"target": path_obj.name, "files": len(target_files)},
            tags=["audit"],
            metadata={"audit_id": ctx.audit_id, "target": path_obj.name},
        ) as root:
            ctx.trace_id = root.trace_id
            report = self._run_audit(ctx, path_obj, target_files, target_path, progress_callback)
            root.update(output={
                "trust_score": report.trust_score,
                "recommendation": report.recommendation,
                "findings": report.total_findings,
            })
            if report.incomplete_reasons:
                root.warn(f"audit incomplete: {report.incomplete_reasons[0]}")
        return report

    @staticmethod
    def _traced_target_agent(agent_name: str, runner: Callable[[str], List[Dict[str, Any]]]):
        """Wraps a target-level agent (Leak-Hunter, Purana-Saman) so its run is recorded as an agent span."""
        def run(path: str) -> List[Dict[str, Any]]:
            with tracing.observation(f"agent.{agent_name}", as_type="agent", input={"target": Path(path).name}) as span:
                findings = runner(path)
                span.update(output=tracing.summarize_findings(findings))
                errors = [f for f in findings if isinstance(f, dict) and str(f.get("status") or "").upper() == "ERROR"]
                if errors:
                    span.warn(str(errors[0].get("title") or "agent reported an error"))
                return findings
        return run

    def _run_audit(
        self,
        ctx: AuditContext,
        path_obj: Path,
        target_files: List[Path],
        target_path: str,
        progress_callback: Optional[Callable[[str, str], None]],
    ) -> AuditReport:
        """Runs every agent over the discovered files and returns the synthesized report."""
        ctx.add_event("Orchestrator", "started", detail=f"{len(target_files)} file(s)")

        # 4a. Target-level agents do not read the source files, so they run in the background while files are audited.
        #     Purana-Saman's dependency resolution is the slowest step in an audit.
        target_pool = ThreadPoolExecutor(max_workers=2)
        target_futures = {
            agent_name: target_pool.submit(
                tracing.wrap_context(self._traced_target_agent(agent_name, runner)), str(path_obj)
            )
            for agent_name, runner in (
                ("Leak-Hunter", run_leak_hunter),
                ("Purana-Saman", run_purana_saman),
            )
        }

        # 4. Audit each discovered file
        for src_file in target_files:
            rel_path = str(src_file.relative_to(path_obj.parent if path_obj.is_file() else path_obj))
            ctx.files_scanned.append(rel_path)
            file_lang = self.detector.detect_file_language(str(src_file)) or "python"
            adapter = LanguageAdapterRegistry.get_adapter(file_lang)
            test_fw = adapter.testing_framework if adapter else "pytest"

            try:
                with open(src_file, "r", encoding="utf-8") as f:
                    source_code = f.read()
            except Exception as e:
                logger.error(f"Failed to read file {src_file}: {e}")
                ctx.record_failure(
                    "Security-Guard", "File Read Error", f"Could not read file {rel_path}: {str(e)}",
                    file_path=rel_path, severity="MEDIUM",
                )
                continue

            # Jhooti-Docstring: one LLM call per file (skipped without GROQ_API_KEY)
            try:
                with tracing.observation(
                    "agent.Jhooti-Docstring", as_type="agent",
                    input={"file": rel_path, **tracing.describe_text(source_code, "source")},
                ) as span:
                    docstring_findings = run_jhooti_docstring(source_code, rel_path)
                    span.update(output=tracing.summarize_findings(docstring_findings))
                ctx.record(docstring_findings, "Jhooti-Docstring", rel_path)
            except Exception as e:
                logger.warning(f"Jhooti-Docstring failed on {rel_path}: {e}")
                ctx.mark_partial_failure("Jhooti-Docstring", f"{rel_path}: {e}")

            # Fact-Checker and Security-Guard read the whole file, so they run once here, not once per function.
            try:
                # The compiler needs the real absolute path to find sibling imports. Reports keep the relative path.
                absolute_path = str(src_file.resolve())
                file_checks = self.orchestrator.run_file_checks(source_code, absolute_path, file_lang)
                for agent_name, findings in (
                    ("Fact-Checker", file_checks.get("fact_checker", [])),
                    ("Security-Guard", file_checks.get("security_guard", [])),
                ):
                    for finding in findings:
                        if finding.get("file_path") == absolute_path:
                            finding["file_path"] = rel_path
                    ctx.record(findings, agent_name, rel_path)
            except Exception as e:
                logger.exception(f"File checks failed on {rel_path}: {e}")
                ctx.record_failure(
                    "Synthesizer", "Audit Pipeline Failure",
                    f"Audit execution failed on {rel_path}: {str(e)}", file_path=rel_path,
                )

            # Blind-Tester works per function. Each spec is an LLM call plus a sandbox run, so they overlap.
            # The context is not passed in: the Blind-Tester sees the specification only.
            func_specs = self._extract_specifications(source_code, src_file.stem, language=file_lang, testing_framework=test_fw)

            def _run_spec(spec, source_code=source_code, rel_path=rel_path):
                if progress_callback:
                    progress_callback("AGENT_START", f"Auditing '{spec.function_name}' in {rel_path}...")
                try:
                    return self.orchestrator.run_spec_checks(source_code, spec, rel_path), None
                except Exception as e:
                    return [], e

            with ThreadPoolExecutor(max_workers=max(1, min(SPEC_WORKERS, len(func_specs) or 1))) as pool:
                for spec_findings, error in pool.map(tracing.wrap_context(_run_spec), func_specs):
                    if error is not None:
                        logger.exception(f"Orchestration failure on {rel_path}: {error}")
                        ctx.record_failure(
                            "Synthesizer", "Audit Pipeline Failure",
                            f"Audit execution failed on {rel_path}: {str(error)}", file_path=rel_path,
                        )
                        continue
                    # Recorded here, in spec order, so the report is deterministic even with several spec workers.
                    ctx.record(spec_findings, "Blind-Tester", rel_path)

        # 4b. Collect the target-level agents: Leak-Hunter (secrets) and Purana-Saman (dependencies)
        for agent_name, future in target_futures.items():
            try:
                ctx.record(future.result(), agent_name, str(path_obj))
            except Exception as e:
                logger.warning(f"{agent_name} failed on {target_path}: {e}")
                ctx.mark_partial_failure(agent_name, str(e))
        target_pool.shutdown(wait=False)

        # 5. Final Synthesis across all inspected files, read from the shared context
        if progress_callback:
            progress_callback("SYNTHESIZER", "Synthesizing final Trust Score and audit report...")

        def summary_fn(trust_info: Dict[str, Any], contributions: Dict[str, int], total_findings: int) -> str:
            return (
                f"Audit completed across {len(ctx.files_scanned)} file(s). "
                f"Trust Score: {trust_info['trust_score']}/100 ({trust_info['recommendation']}). "
                f"Total findings: {total_findings}."
            )

        ctx.add_event("Synthesizer", "completed")
        with tracing.observation("agent.Synthesizer", as_type="agent") as span:
            report = self.synthesizer.build_report(ctx, agents=VERIFICATION_AGENTS, summary_fn=summary_fn)
            span.update(output={
                "trust_score": report.trust_score,
                "recommendation": report.recommendation,
                "findings": report.total_findings,
                "incomplete": len(report.incomplete_reasons),
            })
        return report


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
                # Python class methods and properties need an instance, so a module-level spec test cannot call them.
                if language == "python" and getattr(fn, "is_method", False):
                    continue
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
