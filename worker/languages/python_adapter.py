"""
Python language adapter.
Provides parsing, AST/runtime introspection API verification, and dependency inspection.
"""
import ast
import inspect
import importlib
import builtins
from typing import Dict, Any, List, Optional
from pathlib import Path

from languages.base import LanguageAdapter
from languages.models import (
    ParsedCodeFile,
    NormalizedFinding,
    VerificationStatus,
    FindingSeverity
)
from languages.universal_parser import UniversalParser


class PythonAdapter(LanguageAdapter):
    """
    Adapter for Python source files (.py).
    Combines Tree-sitter / AST parsing with runtime inspect() and dir() deterministic checks.
    """
    @property
    def language_name(self) -> str:
        return "python"

    @property
    def supported_extensions(self) -> List[str]:
        return [".py"]

    @property
    def testing_framework(self) -> str:
        return "pytest"

    @property
    def capabilities(self) -> Dict[str, bool]:
        return {
            "parsing": True,
            "api_verification": True,
            "dependency_inspection": True,
            "security_analysis": True,
            "test_execution": True
        }

    def parse_code(self, source_code: str, file_path: str = "target.py") -> ParsedCodeFile:
        return UniversalParser.parse(source_code, "python", file_path)

    def inspect_dependencies(self, project_path: str) -> Dict[str, str]:
        deps: Dict[str, str] = {}
        path_obj = Path(project_path)
        req_file = path_obj / "requirements.txt" if path_obj.is_dir() else path_obj.parent / "requirements.txt"
        if req_file.exists():
            try:
                with open(req_file, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith("#"):
                            parts = line.split("==") if "==" in line else [line, "*"]
                            deps[parts[0].strip()] = parts[1].strip() if len(parts) > 1 else "*"
            except Exception:
                pass
        return deps

    def verify_api_usage(
        self,
        parsed_file: ParsedCodeFile,
        project_context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedFinding]:
        findings: List[NormalizedFinding] = []

        # Check for syntax errors first
        try:
            tree = ast.parse(parsed_file.source_code)
        except SyntaxError as e:
            findings.append(NormalizedFinding(
                agent_name="Fact-Checker",
                severity=FindingSeverity.CRITICAL.value,
                status=VerificationStatus.INVALID.value,
                title="Syntax Error",
                description=str(e),
                file_path=parsed_file.file_path,
                line_number=e.lineno or 1,
                evidence={
                    "language": "python",
                    "error_type": "SyntaxError",
                    "detail": str(e)
                },
                recommendation="Fix Python syntax error before proceeding."
            ))
            return findings

        # Map imports from AST for resolution
        imports: Dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    name = alias.asname if alias.asname else alias.name
                    imports[name] = alias.name
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    for alias in node.names:
                        name = alias.asname if alias.asname else alias.name
                        imports[name] = f"{node.module}.{alias.name}"

        # Resolve helper
        def resolve_name(node: ast.expr) -> Optional[str]:
            if isinstance(node, ast.Name):
                return node.id
            elif isinstance(node, ast.Attribute):
                base = resolve_name(node.value)
                if base:
                    return f"{base}.{node.attr}"
            return None

        # Inspect all calls in AST
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue

            api_name = resolve_name(node.func)
            if not api_name:
                raw_name = "unknown_call"
                if isinstance(node.func, ast.Attribute):
                    raw_name = f"*.{node.func.attr}"

                findings.append(NormalizedFinding(
                    agent_name="Fact-Checker",
                    severity=FindingSeverity.INFO.value,
                    status=VerificationStatus.UNRESOLVED.value,
                    title="Unresolved Dynamic Call",
                    description=f"Cannot statically resolve call to '{raw_name}'.",
                    file_path=parsed_file.file_path,
                    line_number=node.lineno,
                    evidence={
                        "language": "python",
                        "called_api": raw_name,
                        "verification": "Dynamic or computed object invocation"
                    },
                    recommendation="Ensure the dynamic method signature matches runtime target."
                ))
                continue

            parts = api_name.split(".")
            base_name = parts[0]

            resolved_full_path = api_name
            if base_name in imports:
                import_path = imports[base_name]
                if len(parts) > 1:
                    resolved_full_path = f"{import_path}.{'.'.join(parts[1:])}"
                else:
                    resolved_full_path = import_path
            elif hasattr(builtins, base_name):
                resolved_full_path = f"builtins.{api_name}"

            resolved_parts = resolved_full_path.split(".")
            target_obj = None

            for i in range(len(resolved_parts), 0, -1):
                mod_candidate = ".".join(resolved_parts[:i])
                try:
                    mod = importlib.import_module(mod_candidate)
                    target_obj = mod
                    attr_parts = resolved_parts[i:]
                    for attr in attr_parts:
                        if hasattr(target_obj, attr):
                            target_obj = getattr(target_obj, attr)
                        else:
                            target_obj = None
                            break
                    if target_obj is not None:
                        break
                except ImportError:
                    continue

            if not target_obj:
                if base_name in imports or hasattr(builtins, base_name) or base_name in ["os", "sys", "json", "re", "math", "datetime"]:
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.HIGH.value,
                        status=VerificationStatus.INVALID.value,
                        title="Non-existent API",
                        description=f"The API '{api_name}' does not exist in the installed environment.",
                        file_path=parsed_file.file_path,
                        line_number=node.lineno,
                        evidence={
                            "language": "python",
                            "called_api": api_name,
                            "resolved_path": resolved_full_path,
                            "verification": "Module or attribute missing from environment"
                        },
                        recommendation=f"Verify spelling or import path for '{api_name}'."
                    ))
                else:
                    title = "Unresolved Import" if api_name == base_name else "Unresolved Dynamic Call"
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.UNRESOLVED.value,
                        title=title,
                        description=f"Cannot resolve module or object for '{api_name}'.",
                        file_path=parsed_file.file_path,
                        line_number=node.lineno,
                        evidence={
                            "language": "python",
                            "called_api": api_name,
                            "verification": "Package not installed in runtime environment"
                        },
                        recommendation="Install package or provide specification mock."
                    ))
                continue

            if not callable(target_obj):
                findings.append(NormalizedFinding(
                    agent_name="Fact-Checker",
                    severity=FindingSeverity.HIGH.value,
                    status=VerificationStatus.INVALID.value,
                    title="Not Callable",
                    description=f"'{api_name}' is not callable.",
                    file_path=parsed_file.file_path,
                    line_number=node.lineno,
                    evidence={
                        "language": "python",
                        "called_api": api_name,
                        "type": str(type(target_obj))
                    },
                    recommendation=f"Ensure '{api_name}' is a function, method, or callable class."
                ))
                continue

            try:
                sig = inspect.signature(target_obj)
            except ValueError:
                findings.append(NormalizedFinding(
                    agent_name="Fact-Checker",
                    severity=FindingSeverity.INFO.value,
                    status=VerificationStatus.UNRESOLVED.value,
                    title="Cannot inspect signature",
                    description=f"Signature for '{api_name}' is not introspectable.",
                    file_path=parsed_file.file_path,
                    line_number=node.lineno,
                    evidence={"language": "python", "called_api": api_name},
                    recommendation="Verify function signature against external library documentation."
                ))
                continue

            valid = True
            provided_kwargs = [kw.arg for kw in node.keywords if kw.arg is not None]

            for kw in provided_kwargs:
                if kw not in sig.parameters:
                    has_kwargs = any(p.kind == inspect.Parameter.VAR_KEYWORD for p in sig.parameters.values())
                    if not has_kwargs:
                        findings.append(NormalizedFinding(
                            agent_name="Fact-Checker",
                            severity=FindingSeverity.MEDIUM.value,
                            status=VerificationStatus.INVALID.value,
                            title="Invalid Keyword Parameter",
                            description=f"Parameter '{kw}' does not exist in '{api_name}'.",
                            file_path=parsed_file.file_path,
                            line_number=node.lineno,
                            evidence={
                                "language": "python",
                                "called_api": api_name,
                                "invalid_param": kw,
                                "valid_parameters": list(sig.parameters.keys())
                            },
                            recommendation=f"Remove or rename invalid parameter '{kw}'."
                        ))
                        valid = False

            provided_args = len(node.args)
            required_params = [
                p.name for p in sig.parameters.values()
                if p.default == inspect.Parameter.empty and p.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD)
            ]

            unmet_required = [p for p in required_params if p not in provided_kwargs]

            if len(unmet_required) > provided_args:
                has_varargs = any(p.kind == inspect.Parameter.VAR_POSITIONAL for p in sig.parameters.values())
                if not has_varargs:
                    missing = unmet_required[provided_args:]
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.HIGH.value,
                        status=VerificationStatus.INVALID.value,
                        title="Missing Required Parameter",
                        description=f"Missing required parameter(s): {', '.join(missing)} for '{api_name}'.",
                        file_path=parsed_file.file_path,
                        line_number=node.lineno,
                        evidence={
                            "language": "python",
                            "called_api": api_name,
                            "missing_parameters": missing
                        },
                        recommendation=f"Provide required argument(s): {', '.join(missing)}."
                    ))
                    valid = False

            if valid:
                findings.append(NormalizedFinding(
                    agent_name="Fact-Checker",
                    severity=FindingSeverity.INFO.value,
                    status=VerificationStatus.VALID.value,
                    title="Valid API Usage",
                    description=f"API '{api_name}' and its arguments are valid.",
                    file_path=parsed_file.file_path,
                    line_number=node.lineno,
                    evidence={
                        "language": "python",
                        "called_api": api_name,
                        "verification": "Verified against Python runtime inspect() signature."
                    },
                    recommendation="No action required."
                ))

        return findings
