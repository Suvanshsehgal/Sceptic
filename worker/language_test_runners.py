"""
Per-language test execution for Blind-Tester.

Each supported language has:
- the files to write into the sandbox work folder (implementation, test file, and any config),
- the command to run inside the sandbox image,
- a parser that turns the runner's output into one shared result format.

Shared result format (same as the Python executor): success, exit_code, passed, failed, failures, raw_stdout,
raw_stderr. Each failure is {"test_name": str, "message": str}. Failure messages end with "[errors: ...]" listing the
exception types found in the output, so the verdict can tell an AssertionError (the spec was tested and failed)
from a crash such as TypeError (the call did not fit the code).
"""
import re
import json
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from xml.etree import ElementTree

SUPPORTED_LANGUAGES = ("python", "javascript", "typescript", "java")
LANGUAGE_ALIASES = {"js": "javascript", "ts": "typescript", "py": "python"}

JUNIT_JAR = "/opt/junit/junit-platform-console-standalone.jar"
JEST_BIN = "/opt/sceptic-js/node_modules/.bin/jest"
TS_JEST = "/opt/sceptic-js/node_modules/ts-jest"
IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ERROR_TYPE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*(?:Error|Exception|Failure))\b")
PYTHON_COMMAND = ["python", "-m", "pytest", "test_generated.py", "-v", "--tb=short", "-p", "no:cacheprovider"]


class UnsupportedLanguage(ValueError):
    pass


def normalize_language(language: Optional[str]) -> str:
    value = (language or "python").strip().lower()
    value = LANGUAGE_ALIASES.get(value, value)
    if value not in SUPPORTED_LANGUAGES:
        raise UnsupportedLanguage(f"Blind-Tester does not run tests for '{language}'.")
    return value


def safe_module_name(name: str) -> str:
    """Module and class names end up in file names and shell commands, so only identifiers are accepted."""
    if not IDENTIFIER.match(name or ""):
        raise ValueError(f"'{name}' is not a valid module name for test execution.")
    return name


def error_tags(text: str) -> List[str]:
    tags = set()
    for match in ERROR_TYPE.findall(text or ""):
        if match in ("AssertionFailedError", "AssertionError") or "expect(" in (text or ""):
            tags.add("AssertionError")
        else:
            tags.add(match)
    if not tags and "expect(" in (text or ""):
        tags.add("AssertionError")
    return sorted(tags)


def _tagged(message: str, text: str) -> str:
    tags = error_tags(text)
    return f"{message} [errors: {', '.join(tags)}]" if tags else message


@dataclass
class RunnerSpec:
    language: str
    impl_file: str
    test_file: str
    extra_files: Dict[str, str] = field(default_factory=dict)
    command: List[str] = field(default_factory=list)
    parse: Callable[[int, str, str], Dict[str, Any]] = None  # (exit_code, stdout, stderr) -> result


def _result(success: bool, exit_code: int, passed: int, failures: List[Dict[str, str]], stdout: str, stderr: str) -> Dict[str, Any]:
    return {
        "success": success,
        "exit_code": exit_code,
        "passed": passed,
        "failed": len(failures),
        "failures": failures,
        "raw_stdout": stdout,
        "raw_stderr": stderr,
    }


def _jest_config(extension: str) -> str:
    transform = (
        "{'^.+\\\\.ts$': ['" + TS_JEST + "', {diagnostics: false, isolatedModules: true}]}"
        if extension == "ts" else "{}"
    )
    return (
        "module.exports = {\n"
        "  rootDir: '/work',\n"
        f"  testMatch: ['**/test_generated.test.{extension}'],\n"
        f"  moduleFileExtensions: ['{extension}', 'js', 'json'],\n"
        "  testEnvironment: 'node',\n"
        "  cacheDirectory: '/tmp/jest-cache',\n"
        "  watchman: false,\n"
        f"  transform: {transform},\n"
        "};\n"
    )


def _parse_jest(exit_code: int, stdout: str, stderr: str) -> Dict[str, Any]:
    start = stdout.find('{"numFailedTestSuites"')
    if start == -1:
        start = stdout.find("{")
    if start == -1:
        return _result(False, exit_code, 0, [{"test_name": "runner", "message": (stderr or stdout)[-500:]}], stdout, stderr)
    try:
        data, _ = json.JSONDecoder().raw_decode(stdout[start:])
    except json.JSONDecodeError:
        return _result(False, exit_code, 0, [{"test_name": "runner", "message": "Jest output could not be read."}], stdout, stderr)

    failures: List[Dict[str, str]] = []
    for suite in data.get("testResults", []):
        suite_message = suite.get("message") or ""
        if suite.get("status") == "failed" and not suite.get("assertionResults"):
            failures.append({"test_name": "test_collection_or_import", "message": _tagged(suite_message.strip()[:500], suite_message)})
        for assertion in suite.get("assertionResults", []):
            if assertion.get("status") != "failed":
                continue
            text = "\n".join(assertion.get("failureMessages") or [])
            first_line = text.strip().splitlines()[0] if text.strip() else "failed"
            failures.append({"test_name": assertion.get("title") or "unnamed", "message": _tagged(first_line[:500], text)})

    passed = int(data.get("numPassedTests", 0))
    success = bool(data.get("success")) and not failures
    return _result(success, exit_code, passed, failures, stdout, stderr)


def _parse_junit(exit_code: int, stdout: str, stderr: str) -> Dict[str, Any]:
    if "@@COMPILE_FAILED" in stdout:
        return _result(False, exit_code, 0, [{"test_name": "compilation", "message": _tagged(stderr.strip()[-800:], stderr)}], stdout, stderr)
    if "@@XML_START" not in stdout or "@@XML_END" not in stdout:
        return _result(False, exit_code, 0, [{"test_name": "runner", "message": (stderr or stdout)[-500:]}], stdout, stderr)
    xml_text = stdout.split("@@XML_START", 1)[1].split("@@XML_END", 1)[0].strip()
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError:
        return _result(False, exit_code, 0, [{"test_name": "runner", "message": "JUnit report could not be read."}], stdout, stderr)

    failures: List[Dict[str, str]] = []
    passed = 0
    for case in root.iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            passed += 1
            continue
        kind = problem.get("type") or ""
        text = f"{kind}: {problem.get('message') or ''}\n{problem.text or ''}"
        headline = (problem.get("message") or kind or "failed").splitlines()[0][:500]
        failures.append({"test_name": case.get("name") or "unnamed", "message": _tagged(headline, text)})
    success = not failures and exit_code == 0
    return _result(success, exit_code, passed, failures, stdout, stderr)


def runner_spec(language: str, module: str) -> RunnerSpec:
    """Returns what to write and run for one language and one module name."""
    language = normalize_language(language)
    module = safe_module_name(module) if language == "java" else module
    if language == "python":
        return RunnerSpec(
            language="python",
            impl_file=f"{module}.py",
            test_file="test_generated.py",
            command=list(PYTHON_COMMAND),
            parse=None,  # Python results are read by the pytest parser in blind_tester.py
        )
    if language in ("javascript", "typescript"):
        extension = "js" if language == "javascript" else "ts"
        return RunnerSpec(
            language=language,
            impl_file=f"{module}.{extension}",
            test_file=f"test_generated.test.{extension}",
            extra_files={"jest.config.js": _jest_config(extension)},
            command=["sh", "-c", f"{JEST_BIN} --config /work/jest.config.js --json --ci"],
            parse=_parse_jest,
        )
    # java
    test_class = f"{module}Test"
    command = [
        "sh", "-c",
        "mkdir -p /tmp/classes && "
        f"javac -d /tmp/classes -cp {JUNIT_JAR} *.java; status=$?; "
        "if [ $status -ne 0 ]; then echo '@@COMPILE_FAILED'; exit 1; fi; "
        f"java -jar {JUNIT_JAR} -cp /tmp/classes --select-class {test_class} "
        "--details=none --disable-ansi-colors --reports-dir /tmp/junit-reports >/dev/null 2>&1; "
        "echo '@@XML_START'; cat /tmp/junit-reports/TEST-junit-jupiter.xml; echo '@@XML_END'",
    ]
    return RunnerSpec(
        language="java",
        impl_file=f"{module}.java",
        test_file=f"{test_class}.java",
        command=command,
        parse=_parse_junit,
    )
