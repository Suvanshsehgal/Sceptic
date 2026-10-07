"""
Java language adapter.
Provides parsing, class/method extraction, Maven/Gradle dependency inspection,
and deterministic standard Java API verification.
"""
import re
from pathlib import Path
from typing import Dict, Any, List, Optional
import xml.etree.ElementTree as ET

from languages.base import LanguageAdapter
from languages.models import (
    ParsedCodeFile,
    NormalizedFinding,
    VerificationStatus,
    FindingSeverity,
    CodeCall
)
from languages.universal_parser import UniversalParser

# Standard JDK packages and core classes/methods for deterministic ground truth
KNOWN_JDK_APIS: Dict[str, Dict[str, List[str]]] = {
    "java.lang.System": {
        "methods": ["currentTimeMillis", "nanoTime", "exit", "gc", "getenv", "getProperty", "arraycopy"],
        "fields": ["out", "err", "in"]
    },
    "java.lang.Math": {
        "methods": ["abs", "max", "min", "sqrt", "pow", "sin", "cos", "tan", "floor", "ceil", "round", "random"],
        "fields": ["PI", "E"]
    },
    "java.lang.String": {
        "methods": ["length", "charAt", "substring", "indexOf", "contains", "replace", "toLowerCase", "toUpperCase", "trim", "split", "valueOf", "equals", "equalsIgnoreCase", "startsWith", "endsWith", "isEmpty", "getBytes"]
    },
    "java.util.Collections": {
        "methods": ["sort", "reverse", "shuffle", "unmodifiableList", "unmodifiableSet", "unmodifiableMap", "singletonList", "emptyList", "emptySet", "emptyMap"]
    },
    "java.util.Arrays": {
        "methods": ["sort", "binarySearch", "equals", "fill", "copyOf", "copyOfRange", "asList", "toString", "stream"]
    },
    "java.util.Objects": {
        "methods": ["requireNonNull", "equals", "hashCode", "isNull", "nonNull", "toString"]
    },
    "java.io.File": {
        "methods": ["exists", "isFile", "isDirectory", "getName", "getPath", "getAbsolutePath", "length", "delete", "mkdir", "mkdirs", "createNewFile", "listFiles"]
    }
}


class JavaAdapter(LanguageAdapter):
    """
    Adapter for Java source files (.java).
    Extracts classes, methods, imports, and calls, and validates standard JDK / project APIs deterministically.
    """
    @property
    def language_name(self) -> str:
        return "java"

    @property
    def supported_extensions(self) -> List[str]:
        return [".java"]

    @property
    def testing_framework(self) -> str:
        return "JUnit"

    @property
    def capabilities(self) -> Dict[str, bool]:
        return {
            "parsing": True,
            "api_verification": True,
            "dependency_inspection": True,
            "security_analysis": True,
            "test_execution": False
        }

    def parse_code(self, source_code: str, file_path: str = "Target.java") -> ParsedCodeFile:
        return UniversalParser.parse(source_code, "java", file_path)

    def inspect_dependencies(self, project_path: str) -> Dict[str, str]:
        deps: Dict[str, str] = {}
        path_obj = Path(project_path)
        dir_obj = path_obj if path_obj.is_dir() else path_obj.parent

        # 1. Maven pom.xml
        pom_file = dir_obj / "pom.xml"
        if pom_file.exists():
            try:
                tree = ET.parse(pom_file)
                root = tree.getroot()
                # strip XML namespace
                ns = ""
                if root.tag.startswith("{"):
                    ns = root.tag.split("}")[0] + "}"
                for dep in root.findall(f".//{ns}dependency"):
                    g = dep.find(f"{ns}groupId")
                    a = dep.find(f"{ns}artifactId")
                    v = dep.find(f"{ns}version")
                    g_text = g.text.strip() if g is not None and g.text else ""
                    a_text = a.text.strip() if a is not None and a.text else ""
                    v_text = v.text.strip() if v is not None and v.text else "*"
                    if g_text and a_text:
                        deps[f"{g_text}:{a_text}"] = v_text
            except Exception:
                pass

        # 2. Gradle build.gradle / build.gradle.kts
        for gradle_name in ("build.gradle", "build.gradle.kts"):
            gradle_file = dir_obj / gradle_name
            if gradle_file.exists():
                try:
                    with open(gradle_file, "r", encoding="utf-8") as f:
                        for line in f:
                            match = re.search(r"implementation\s+['\"]([^'\"]+)['\"]", line)
                            if match:
                                dep_str = match.group(1)
                                parts = dep_str.split(":")
                                if len(parts) >= 2:
                                    deps[f"{parts[0]}:{parts[1]}"] = parts[2] if len(parts) > 2 else "*"
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
                    title="Java Syntax Error",
                    description=err,
                    file_path=parsed_file.file_path,
                    line_number=1,
                    evidence={"language": "java", "detail": err},
                    recommendation="Fix Java syntax errors before proceeding."
                ))
            return findings

        # Map imported classes: simple_name -> full_class
        imported_classes: Dict[str, str] = {}
        for imp in parsed_file.imports:
            mod = imp.module
            simple_name = mod.rsplit(".", 1)[-1]
            imported_classes[simple_name] = mod

        # Implicit java.lang imports
        for core_class in ["System", "Math", "String", "Object", "Integer", "Double", "Boolean", "Thread"]:
            if core_class not in imported_classes:
                imported_classes[core_class] = f"java.lang.{core_class}"

        # Known local methods from parsed_file
        local_methods = {f.name for f in parsed_file.functions}

        # Inspect method calls
        for call in parsed_file.calls:
            callee = call.callee_name
            line_no = call.line_number

            # Pattern: TargetClass.methodName(...) or obj.methodName(...)
            if "." in callee:
                target, method = callee.rsplit(".", 1)
                full_class = imported_classes.get(target)

                if full_class and full_class in KNOWN_JDK_APIS:
                    api_info = KNOWN_JDK_APIS[full_class]
                    valid_methods = api_info.get("methods", [])
                    if method in valid_methods:
                        findings.append(NormalizedFinding(
                            agent_name="Fact-Checker",
                            severity=FindingSeverity.INFO.value,
                            status=VerificationStatus.VALID.value,
                            title="Valid API Usage",
                            description=f"JDK method '{full_class}.{method}' is valid.",
                            file_path=parsed_file.file_path,
                            line_number=line_no,
                            evidence={
                                "language": "java",
                                "class": full_class,
                                "method": method,
                                "verification": "JDK ground truth verification."
                            },
                            recommendation="No action required."
                        ))
                    else:
                        findings.append(NormalizedFinding(
                            agent_name="Fact-Checker",
                            severity=FindingSeverity.HIGH.value,
                            status=VerificationStatus.INVALID.value,
                            title="Non-existent API",
                            description=f"Method '{method}' does not exist on '{full_class}'.",
                            file_path=parsed_file.file_path,
                            line_number=line_no,
                            evidence={
                                "language": "java",
                                "class": full_class,
                                "method": method,
                                "valid_methods": valid_methods
                            },
                            recommendation=f"Verify available methods on '{full_class}'."
                        ))
                else:
                    # External or dynamic instance call
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.UNRESOLVED.value,
                        title="Unresolved Java Call",
                        description=f"Cannot statically resolve method '{method}' on instance/class '{target}'.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={
                            "language": "java",
                            "target": target,
                            "method": method,
                            "verification": "Requires runtime classpath or dependency symbol resolution."
                        },
                        recommendation="Ensure dependency is compiled and available in classpath."
                    ))
            else:
                # Direct method invocation without qualifier
                if callee in local_methods:
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.VALID.value,
                        title="Valid Local Method Call",
                        description=f"Local method '{callee}' is defined in this file.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={"language": "java", "method": callee},
                        recommendation="No action required."
                    ))
                else:
                    findings.append(NormalizedFinding(
                        agent_name="Fact-Checker",
                        severity=FindingSeverity.INFO.value,
                        status=VerificationStatus.UNRESOLVED.value,
                        title="Unresolved Local Method",
                        description=f"Method '{callee}' is not defined in this class scope.",
                        file_path=parsed_file.file_path,
                        line_number=line_no,
                        evidence={"language": "java", "method": callee},
                        recommendation="Ensure method is inherited from superclass or imported statically."
                    ))

        return findings
