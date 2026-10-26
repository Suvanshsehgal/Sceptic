"""
Compiler-backed Fact-Checker for JavaScript, TypeScript, and Java.

The Fact-Checker's list-based checks only know a few standard APIs. These checks use the real compilers instead:
- JavaScript and TypeScript: tsc (TypeScript 5.6.3, pinned in worker/tools/js) with checkJs, resolving imports
  from the project's node_modules. The type checker reads .d.ts files and never runs the audited code.
- Java: javac with -proc:none, using the project's Maven classpath when it can be resolved offline.
  javac compiles the file but never runs it.

Verdicts:
- INVALID: a method, property, or name does not exist, or a call does not fit the signature.
- UNRESOLVED: a dependency is missing from the environment, so the compiler cannot check the calls that use it.
- INVALID (CRITICAL): syntax error.

If the compiler is not installed, verify() returns None and the caller uses the list-based checks.
"""
import os
import re
import json
import shutil
import logging
import tempfile
import subprocess
from typing import Any, Dict, List, Optional

logger = logging.getLogger("sceptic.compiler_verifier")

WORKER_DIR = os.path.dirname(os.path.abspath(__file__))
TOOLS_JS_DIR = os.path.join(WORKER_DIR, "tools", "js")
TSC_BIN = os.path.join(TOOLS_JS_DIR, "node_modules", "typescript", "bin", "tsc")
TOOLS_TYPES = os.path.join(TOOLS_JS_DIR, "node_modules", "@types")
COMPILER_TIMEOUT_SECONDS = 120

COMPILER_LANGUAGES = ("javascript", "typescript", "java")

TSC_LINE = re.compile(r"^(?P<file>.+?)\((?P<line>\d+),(?P<col>\d+)\): (?P<kind>error|warning) (?P<code>TS\d+): (?P<msg>.*)$")
JAVAC_LINE = re.compile(r"^(?P<file>.+\.java):(?P<line>\d+): error: (?P<msg>.*)$")


def _finding(title: str, description: str, status: str, severity: str, file_path: str,
             line: Optional[int], evidence: Dict[str, Any], recommendation: str) -> Dict[str, Any]:
    return {
        "agent_name": "Fact-Checker",
        "severity": severity,
        "status": status,
        "title": title,
        "description": description,
        "file_path": file_path,
        "line_number": line,
        "evidence": evidence,
        "recommendation": recommendation,
    }


def find_project_root(file_path: str, marker: str) -> Optional[str]:
    """Walks up from a file until the marker (for example node_modules or pom.xml) is found."""
    current = os.path.dirname(os.path.abspath(file_path))
    while True:
        if os.path.exists(os.path.join(current, marker)):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


# ---------------------------------------------------------------------------
# JavaScript and TypeScript (tsc)
# ---------------------------------------------------------------------------

TSC_RULES = {
    "TS2339": ("INVALID", "HIGH", "Non-existent API", "Property or method does not exist on its type."),
    "TS2551": ("INVALID", "HIGH", "Non-existent API", "Property or method does not exist (did you mean a similar name?)."),
    "TS2554": ("INVALID", "MEDIUM", "Signature mismatch", "The call passes the wrong number of arguments."),
    "TS2555": ("INVALID", "MEDIUM", "Signature mismatch", "The call passes the wrong number of arguments."),
    "TS2558": ("INVALID", "MEDIUM", "Signature mismatch", "The call passes the wrong number of type arguments."),
    "TS2345": ("INVALID", "MEDIUM", "Type mismatch", "An argument does not match the parameter type."),
    "TS2304": ("INVALID", "MEDIUM", "Undefined name", "A name is used that is not declared or imported."),
    "TS2307": ("UNRESOLVED", "INFO", "Unresolved import", "The module is not installed, so its calls cannot be checked."),
}


def _tsc_available() -> bool:
    return shutil.which("node") is not None and os.path.exists(TSC_BIN)


STAGED_EXTENSIONS = (".ts", ".tsx", ".js", ".jsx")
MAX_STAGED_FILES = 300
MAX_STAGED_FILE_BYTES = 512 * 1024
STAGE_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "coverage"}


def _same_file(reported: str, expected: str) -> bool:
    return os.path.normcase(os.path.normpath(reported)) == os.path.normcase(os.path.normpath(expected))


def _stage_sources(file_path: str, source_code: str, tmp: str) -> str:
    """
    Copies the project's source tree (the nearest 'src' folder, or the file's own folder) into tmp, so that relative
    imports such as '../api' resolve. Without this, imported types are unknown and tsc reports cascades of
    false errors. Returns the path of the audited file inside the staged tree, with the audited source_code written.
    """
    abs_file = os.path.abspath(file_path)
    src_root = None
    current = os.path.dirname(abs_file)
    while True:
        if os.path.basename(current) == "src":
            src_root = current
            break
        parent = os.path.dirname(current)
        if parent == current:
            break
        current = parent
    if src_root is None:
        src_root = os.path.dirname(abs_file)

    staged_root = os.path.join(tmp, "src")
    copied = 0
    for dirpath, dirnames, filenames in os.walk(src_root):
        dirnames[:] = [d for d in dirnames if d not in STAGE_SKIP_DIRS]
        for name in filenames:
            if copied >= MAX_STAGED_FILES:
                break
            if not name.endswith(STAGED_EXTENSIONS):
                continue
            full = os.path.join(dirpath, name)
            if _same_file(full, abs_file):
                continue
            try:
                if os.path.getsize(full) > MAX_STAGED_FILE_BYTES:
                    continue
                dest = os.path.join(staged_root, os.path.relpath(full, src_root))
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                shutil.copyfile(full, dest)
                copied += 1
            except OSError:
                continue

    rel_target = os.path.relpath(abs_file, src_root) if abs_file.startswith(src_root + os.sep) else os.path.basename(abs_file)
    target = os.path.join(staged_root, rel_target)
    os.makedirs(os.path.dirname(target), exist_ok=True)
    with open(target, "w", encoding="utf-8") as f:
        f.write(source_code)
    return target


def _verify_js_ts(source_code: str, file_path: str, language: str) -> Optional[List[Dict[str, Any]]]:
    if not _tsc_available():
        return None
    # Keep the real extension: .tsx and .jsx files contain JSX, which tsc only parses when the file is named that way.
    is_jsx = os.path.splitext(file_path)[1].lower() in (".tsx", ".jsx")
    project_root = find_project_root(file_path, "node_modules") or os.path.dirname(os.path.abspath(file_path))
    project_node_modules = os.path.join(project_root, "node_modules")

    with tempfile.TemporaryDirectory() as tmp:
        check_file = _stage_sources(file_path, source_code, tmp)
        type_roots = [TOOLS_TYPES]
        if os.path.isdir(os.path.join(project_node_modules, "@types")):
            type_roots.append(os.path.join(project_node_modules, "@types"))
        config = {
            "compilerOptions": {
                "allowJs": True,
                "checkJs": True,
                "noEmit": True,
                "strict": False,
                "target": "ES2020",
                "module": "commonjs",
                "moduleResolution": "node",
                "skipLibCheck": True,
                "esModuleInterop": True,
                "allowSyntheticDefaultImports": True,
                "resolveJsonModule": True,
                **({"jsx": "react-jsx"} if is_jsx else {}),
                "baseUrl": tmp,
                "paths": {"*": [os.path.join(project_node_modules, "*"), os.path.join(project_node_modules, "@types", "*")]},
                "typeRoots": type_roots,
                "types": ["node"],
            },
            "files": [check_file],
        }
        config_path = os.path.join(tmp, "tsconfig.json")
        with open(config_path, "w", encoding="utf-8") as f:
            json.dump(config, f)

        try:
            proc = subprocess.run(
                ["node", TSC_BIN, "-p", config_path, "--pretty", "false"],
                capture_output=True, text=True, encoding="utf-8", errors="replace",
                timeout=COMPILER_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
            )
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(f"tsc could not run: {e}")
            return None

        findings: List[Dict[str, Any]] = []
        syntax_errors: List[Dict[str, Any]] = []
        for raw in proc.stdout.splitlines():
            match = TSC_LINE.match(raw.strip())
            if not match or match.group("kind") != "error":
                continue
            # Staged project files are type-checked too, so only report diagnostics from the file being audited.
            if not _same_file(match.group("file"), check_file):
                continue
            code = match.group("code")
            message = match.group("msg")
            line = int(match.group("line"))
            if code.startswith("TS1"):  # syntax errors are TS1xxx
                syntax_errors.append({"message": message, "line": line, "code": code})
                continue
            rule = TSC_RULES.get(code)
            if rule is None:
                continue  # diagnostics outside the verification rules (style, implicit any) are not reported
            status, severity, title, description = rule
            findings.append(_finding(
                title, f"{description} {message}", status, severity, file_path, line,
                {"language": language, "tool": "tsc", "code": code}, "Correct the call so it matches the declared API.",
            ))

        # One broken token makes the parser report a long cascade of follow-on errors. The first one is the real defect,
        # so it is reported once, and the rest are counted instead of each costing a CRITICAL penalty.
        if syntax_errors:
            first = syntax_errors[0]
            findings.insert(0, _finding(
                "Syntax Error", first["message"], "INVALID", "CRITICAL", file_path, first["line"],
                {"language": language, "tool": "tsc", "code": first["code"],
                 "follow_on_syntax_errors": len(syntax_errors) - 1},
                "Fix the syntax error at this line first, then re-run the audit. Later errors often disappear with it.",
            ))

        if proc.returncode == 0 or not findings:
            findings.append(_finding(
                "Valid API Usage",
                "tsc found no errors. Calls on values typed any, or with no declared type, are not verified.",
                "VALID", "INFO", file_path, None,
                {"language": language, "tool": "tsc", "project_node_modules": os.path.isdir(project_node_modules)},
                "No action required.",
            ))
    return findings


# ---------------------------------------------------------------------------
# Java (javac)
# ---------------------------------------------------------------------------

def _javac_available() -> bool:
    return shutil.which("javac") is not None


def _maven_classpath(file_path: str, tmp: str) -> (str, str):
    """Returns (classpath, note). Uses offline Maven only, so no network access happens here."""
    pom_root = find_project_root(file_path, "pom.xml")
    mvn = os.getenv("MVN_PATH", "").strip() or shutil.which("mvn")
    if pom_root is None or not mvn:
        return "", "No Maven project or mvn not installed; dependencies are not on the classpath."
    out_file = os.path.join(tmp, "classpath.txt")
    try:
        proc = subprocess.run(
            [mvn, "-q", "-o", "-f", os.path.join(pom_root, "pom.xml"),
             "dependency:build-classpath", f"-Dmdep.outputFile={out_file}"],
            capture_output=True, text=True, timeout=COMPILER_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "", "Maven did not resolve dependencies in time; dependency calls are unresolved."
    if proc.returncode != 0 or not os.path.exists(out_file):
        return "", "Dependencies are not in the offline Maven cache; dependency calls are unresolved."
    with open(out_file, encoding="utf-8") as f:
        return f.read().strip(), "Dependencies resolved offline from the Maven cache."


def _verify_java(source_code: str, file_path: str) -> Optional[List[Dict[str, Any]]]:
    if not _javac_available():
        return None
    stem = os.path.splitext(os.path.basename(file_path))[0] or "Target"
    with tempfile.TemporaryDirectory() as tmp:
        source_path = os.path.join(tmp, f"{stem}.java")
        with open(source_path, "w", encoding="utf-8") as f:
            f.write(source_code)
        classpath, note = _maven_classpath(file_path, tmp)
        out_dir = os.path.join(tmp, "out")
        os.makedirs(out_dir, exist_ok=True)
        cmd = ["javac", "-proc:none", "-implicit:none", "-d", out_dir]
        if classpath:
            cmd += ["-cp", classpath]
        cmd.append(source_path)
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                                  timeout=COMPILER_TIMEOUT_SECONDS, stdin=subprocess.DEVNULL)
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(f"javac could not run: {e}")
            return None

        lines = proc.stderr.splitlines()
        findings: List[Dict[str, Any]] = []
        for index, raw in enumerate(lines):
            match = JAVAC_LINE.match(raw.strip())
            if not match:
                continue
            message = match.group("msg")
            line = int(match.group("line"))
            symbol = ""
            for follow in lines[index + 1:index + 6]:
                if "symbol:" in follow:
                    symbol = follow.split("symbol:", 1)[1].strip()
                    break
            evidence = {"language": "java", "tool": "javac", "symbol": symbol or None, "classpath": note}
            if message.startswith("package ") and "does not exist" in message:
                findings.append(_finding(
                    "Unresolved Import", f"{message}. Its calls cannot be checked without the dependency.",
                    "UNRESOLVED", "INFO", file_path, line, evidence,
                    "Make the dependency available (pom.xml, offline Maven cache) and re-run the audit.",
                ))
            elif message.startswith("cannot find symbol"):
                findings.append(_finding(
                    "Non-existent API", f"{message}{' ' + symbol if symbol else ''}.", "INVALID", "HIGH", file_path, line,
                    evidence, "Check the spelling and the available methods of the class.",
                ))
            elif "cannot be applied to given types" in message or "no suitable" in message:
                findings.append(_finding(
                    "Signature mismatch", message, "INVALID", "MEDIUM", file_path, line, evidence,
                    "Pass arguments that match the method's declared parameters.",
                ))
            elif message.startswith("incompatible types"):
                findings.append(_finding(
                    "Type mismatch", message, "INVALID", "MEDIUM", file_path, line, evidence,
                    "Use a value of the declared type.",
                ))
            elif any(text in message for text in ("expected", "illegal start", "reached end of file", "class, interface")):
                findings.append(_finding(
                    "Syntax Error", message, "INVALID", "CRITICAL", file_path, line, evidence, "Fix the syntax error.",
                ))
            else:
                findings.append(_finding(
                    "Compilation Error", message, "INVALID", "MEDIUM", file_path, line, evidence,
                    "Fix the compilation error.",
                ))

        if proc.returncode == 0 and not findings:
            findings.append(_finding(
                "Valid API Usage", "javac compiled this file, so every call in it was type-checked.", "VALID", "INFO",
                file_path, None, {"language": "java", "tool": "javac", "classpath": note}, "No action required.",
            ))
    return findings


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def verify(source_code: str, file_path: str, language: str) -> Optional[List[Dict[str, Any]]]:
    """
    Compiler verification for JavaScript, TypeScript, or Java.
    Returns findings, or None when the compiler is not installed (the caller then uses the list-based checks).
    """
    if language in ("javascript", "typescript"):
        return _verify_js_ts(source_code, file_path, language)
    if language == "java":
        return _verify_java(source_code, file_path)
    return None
