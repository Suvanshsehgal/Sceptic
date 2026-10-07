"""
JavaScript and TypeScript language adapters.
Provides parsing, function/class/import/call extraction, package.json dependency inspection,
and deterministic standard JS/TS runtime API verification.
"""
import json
from pathlib import Path
from typing import Dict, Any, List, Optional

from languages.base import LanguageAdapter
from languages.models import (
    ParsedCodeFile,
    NormalizedFinding,
    VerificationStatus,
    FindingSeverity
)
from languages.universal_parser import UniversalParser

# Standard built-in JavaScript / Node.js runtime globals and methods
KNOWN_JS_GLOBALS: Dict[str, List[str]] = {
    "Math": ["abs", "max", "min", "sqrt", "pow", "sin", "cos", "tan", "floor", "ceil", "round", "random", "trunc"],
    "JSON": ["parse", "stringify"],
    "Object": ["keys", "values", "entries", "assign", "freeze", "seal", "create", "getPrototypeOf", "hasOwn", "is"],
    "Array": ["isArray", "from", "of"],
    "Promise": ["all", "allSettled", "race", "any", "resolve", "reject"],
    "console": ["log", "error", "warn", "info", "debug", "trace", "time", "timeEnd", "table"],
    "Number": ["isInteger", "isNaN", "isFinite", "parseFloat", "parseInt"],
    "String": ["fromCharCode", "fromCodePoint", "raw"],
    "Date": ["now", "parse", "UTC"]
}


class BaseJavaScriptAdapter(LanguageAdapter):
    """
    Shared base adapter for JavaScript and TypeScript.
    """
    def inspect_dependencies(self, project_path: str) -> Dict[str, str]:
        deps: Dict[str, str] = {}
        path_obj = Path(project_path)
        dir_obj = path_obj if path_obj.is_dir() else path_obj.parent

        pkg_json = dir_obj / "package.json"
        if pkg_json.exists():
            try:
                with open(pkg_json, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for k in ("dependencies", "devDependencies", "peerDependencies"):
                        if k in data and isinstance(data[k], dict):
                            deps.update(data[k])
            except Exception:
                pass

        return deps

    def verify_api_usage(
        self,
        parsed_file: ParsedCodeFile,
        project_context: Optional[Dict[str, Any]] = None
    ) -> List[NormalizedFinding]:
        findings: List[NormalizedFinding] = []

        if parsed_file.syntax_errors:
            for err in parsed_file.syntax_errors:
                findings.append(NormalizedFinding(
                    agent_name="Fact-Checker",
                    severity=FindingSeverity.CRITICAL.value,
                    status=VerificationStatus.INVALID.value,
                    title=f"{self.language_name.capitalize()} Syntax Error",
                    description=err,
                    file_path=parsed_file.file_path,
                    line_number=1,
                    evidence={"language": self.language_name, "detail": err},
                    recommendation="Fix syntax errors before proceeding."
                ))
            return findings

        # Known local functions defined in file
        local_functions = {f.name for f in parsed_file.functions}

        # Inspect function and method calls
        for call in parsed_file.calls:
            callee = call.callee_name
            line_no = call.line_number

            # Pattern: Object.method(..)
            if "." in callee:
                target, method = callee.rsplit(".", 1)

                if target in KNOWN_JS_GLOBALS:
                    valid_methods = KNOWN_JS_GLOBALS[target]
                    if method in valid_methods:
                        findings.append(NormalizedFinding(
                            agent_name="Fact-Checker",
                            severity=FindingSeverity.INFO.value,
                            status=VerificationStatus.VALID.value,
                            title="Valid API Usage",
                            description=f"Standard JS API '{target}.{method}' is valid.",
                            file_path=parsed_file.file_path,
                            line_number=line_no,
                            evidence={
                                "language": self.language_name,
                                "target": target,
                                "method": method,
                                "verification": "Standard JavaScript runtime global."
                            },
                            recommendation="No action required."
                        ))
                    else:
                        findings.append(NormalizedFinding(
                            agent_name="Fact-Checker",
                            severity=FindingSeverity.HIGH.value,
                            status=VerificationStatus.INVALID.value,
                            title="Non-existent API",
                            description=f"Method '{method}' does not exist on standard global '{target}'.",
                            file_path=parsed_file.file_path,
                            line_number=line_no,
                            evidence={
                                "language": self.language_name,
                                "target": target,
                                "method": method,
                                "valid_methods": valid_methods
                            },
                            recommendation=f"Check method spelling for global '{target}'."
                        ))
                else:
                    # Dynamic invocation or package method
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.UNRESOLVED.value,
                        title=f"Unresolved {self.language_name.capitalize()} Call",
                        description=f"Cannot statically resolve method '{method}' on object '{target}'.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={
                            "language": self.language_name,
                            "target": target,
                            "method": method,
                            "verification": "Requires dynamic runtime or TypeScript type checker."
                        },
                        recommendation="Verify object definition or imported package exports."
                    ))
            else:
                if callee in local_functions:
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.VALID.value,
                        title="Valid Local Function Call",
                        description=f"Function '{callee}' is declared in this file.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={"language": self.language_name, "function": callee},
                        recommendation="No action required."
                    ))
                elif callee in ("require", "parseInt", "parseFloat", "setTimeout", "clearTimeout", "setInterval", "clearInterval", "fetch"):
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.VALID.value,
                        title="Valid Global Function Call",
                        description=f"Standard global function '{callee}' is valid.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={"language": self.language_name, "function": callee},
                        recommendation="No action required."
                    ))
                else:
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.UNRESOLVED.value,
                        title=f"Unresolved {self.language_name.capitalize()} Function",
                        description=f"Function '{callee}' is not declared locally.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={"language": self.language_name, "function": callee},
                        recommendation="Ensure function is imported or declared."
                    ))

        return findings


class JavaScriptAdapter(BaseJavaScriptAdapter):
    """
    Adapter for JavaScript source files (.js, .jsx, .mjs, .cjs).
    """
    @property
    def language_name(self) -> str:
        return "javascript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".js", ".jsx", ".mjs", ".cjs"]

    @property
    def testing_framework(self) -> str:
        return "Jest"

    @property
    def capabilities(self) -> Dict[str, bool]:
        return {
            "parsing": True,
            "api_verification": True,
            "dependency_inspection": True,
            "security_analysis": True,
            "test_execution": False
        }

    def parse_code(self, source_code: str, file_path: str = "target.js") -> ParsedCodeFile:
        return UniversalParser.parse(source_code, "javascript", file_path)


class TypeScriptAdapter(BaseJavaScriptAdapter):
    """
    Adapter for TypeScript source files (.ts, .tsx, .mts, .cts).
    """
    @property
    def language_name(self) -> str:
        return "typescript"

    @property
    def supported_extensions(self) -> List[str]:
        return [".ts", ".tsx", ".mts", ".cts"]

    @property
    def testing_framework(self) -> str:
        return "Jest"

    @property
    def capabilities(self) -> Dict[str, bool]:
        return {
            "parsing": True,
            "api_verification": True,
            "dependency_inspection": True,
            "security_analysis": True,
            "test_execution": False
        }

    def parse_code(self, source_code: str, file_path: str = "target.ts") -> ParsedCodeFile:
        return UniversalParser.parse(source_code, "typescript", file_path)
