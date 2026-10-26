"""
Tests for full support of JavaScript, TypeScript, and Java next to Python: test execution, compiler-backed Fact-Checker,
Semgrep packs, scanner fail-closed behavior, and the Maven dependency audit.

Tests that need an external tool (tsc, javac, Docker and the sandbox image, osv-scanner) are skipped when the tool is
missing, so the suite still runs on a bare machine. CI installs every tool, so nothing is skipped there.
"""
import os
import shutil
import subprocess
from types import SimpleNamespace

import pytest

import compiler_verifier
import dependency_audit
import language_test_runners as ltr
import security_guard
from blind_tester import BlindTestExecutor, BlindTestGenerator, SpecificationMetadata, run_blind_test
from fact_checker import FactCheckerAgent
from security_guard import run_security_scan


def _docker_image_ready() -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        probe = subprocess.run(["docker", "image", "inspect", "sceptic-sandbox:latest"],
                               capture_output=True, timeout=30, stdin=subprocess.DEVNULL)
    except (OSError, subprocess.TimeoutExpired):
        return False
    return probe.returncode == 0


requires_sandbox = pytest.mark.skipif(not _docker_image_ready(), reason="Docker or sceptic-sandbox:latest not available")
requires_tsc = pytest.mark.skipif(not compiler_verifier._tsc_available(), reason="tsc (worker/tools/js) not installed")
requires_javac = pytest.mark.skipif(shutil.which("javac") is None, reason="javac not installed")
requires_osv = pytest.mark.skipif(
    not (os.getenv("OSV_SCANNER_PATH") or shutil.which("osv-scanner")), reason="osv-scanner not installed"
)


# ---------------------------------------------------------------------------
# Language registry and result parsing (no tools needed)
# ---------------------------------------------------------------------------

def test_language_aliases_and_unsupported_language():
    assert ltr.normalize_language("js") == "javascript"
    assert ltr.normalize_language("TS") == "typescript"
    assert ltr.normalize_language("Java") == "java"
    with pytest.raises(ltr.UnsupportedLanguage):
        ltr.normalize_language("cobol")


def test_java_module_names_must_be_identifiers():
    assert ltr.safe_module_name("Calc") == "Calc"
    with pytest.raises(ValueError):
        ltr.runner_spec("java", "my-file; rm -rf /")


def test_runner_specs_name_the_right_files():
    js = ltr.runner_spec("javascript", "calc")
    assert js.impl_file == "calc.js" and js.test_file == "test_generated.test.js"
    assert "jest.config.js" in js.extra_files
    ts = ltr.runner_spec("typescript", "calc")
    assert ts.impl_file == "calc.ts" and ts.test_file == "test_generated.test.ts"
    java = ltr.runner_spec("java", "Calc")
    assert java.impl_file == "Calc.java" and java.test_file == "CalcTest.java"
    assert any("--select-class CalcTest" in part for part in java.command)


def test_error_tags_map_junit_and_jest_to_assertion():
    assert ltr.error_tags("org.opentest4j.AssertionFailedError: expected 5") == ["AssertionError"]
    assert ltr.error_tags("TypeError: x is not a function") == ["TypeError"]
    assert ltr.error_tags("Error: expect(received).toBe(expected)") == ["AssertionError"]


def test_jest_output_is_parsed_into_failures_and_passes():
    stdout = (
        '{"numFailedTestSuites":0,"numPassedTests":1,"numFailedTests":1,"success":false,'
        '"testResults":[{"status":"failed","message":"","assertionResults":['
        '{"title":"adds","status":"passed","failureMessages":[]},'
        '{"title":"multiplies instead","status":"failed","failureMessages":["Error: expect(received).toBe(expected)\\nExpected: 5"]}'
        "]}]}"
    )
    result = ltr._parse_jest(1, stdout, "")
    assert result["success"] is False
    assert result["passed"] == 1
    assert result["failures"][0]["test_name"] == "multiplies instead"
    assert "[errors: AssertionError]" in result["failures"][0]["message"]


def test_junit_xml_is_parsed_into_failures():
    xml = (
        '<testsuite name="x" tests="2" failures="1">'
        '<testcase name="addsTwoNumbers()" classname="CalcTest"><failure message="expected: &lt;5&gt; but was: &lt;6&gt;" '
        'type="org.opentest4j.AssertionFailedError">trace</failure></testcase>'
        '<testcase name="ok()" classname="CalcTest"/></testsuite>'
    )
    stdout = "@@XML_START\n" + xml + "\n@@XML_END\n"
    result = ltr._parse_junit(1, stdout, "")
    assert result["success"] is False
    assert result["passed"] == 1
    assert result["failures"][0]["test_name"] == "addsTwoNumbers()"
    assert "[errors: AssertionError]" in result["failures"][0]["message"]


def test_junit_compile_failure_is_reported_as_compilation():
    result = ltr._parse_junit(1, "@@COMPILE_FAILED\n", "Calc.java:2: error: illegal start of expression")
    assert result["failures"][0]["test_name"] == "compilation"
    assert "illegal start" in result["failures"][0]["message"]


def test_fallback_tests_for_each_language_check_existence_not_behavior(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    generator = BlindTestGenerator(api_key="")
    js = generator.generate_tests(SpecificationMetadata("add", "Adds.", "Returns a+b.", "calc", language="javascript"))
    assert "typeof m.add).toBe('function')" in js
    ts = generator.generate_tests(SpecificationMetadata("add", "Adds.", "Returns a+b.", "calc", language="typescript"))
    assert "import * as m from './calc'" in ts
    java = generator.generate_tests(SpecificationMetadata("add", "Adds.", "Returns a+b.", "Calc", language="java"))
    assert "class CalcTest" in java and "getDeclaredMethods" in java


def test_llm_prompt_for_each_language_sees_only_the_specification():
    spec_js = SpecificationMetadata("add", "Adds two numbers.", "Returns the sum.", "calc", language="javascript")
    prompt = BlindTestGenerator(api_key="").build_isolated_prompt(spec_js)
    assert "require('./calc')" in prompt and "Adds two numbers." in prompt
    assert "return a + b" not in prompt  # the implementation is never part of the prompt
    spec_java = SpecificationMetadata("add", "Adds two numbers.", "Returns the sum.", "Calc", language="java")
    assert "JUnit 5" in BlindTestGenerator(api_key="").build_isolated_prompt(spec_java)


def test_clean_code_removes_any_language_fence():
    generator = BlindTestGenerator(api_key="")
    assert generator._clean_code("```javascript\nconst a = 1;\n```") == "const a = 1;"
    assert generator._clean_code("```\nplain\n```") == "plain"


def test_osv_severity_mapping_is_never_low_for_unknown():
    assert dependency_audit._osv_severity({"database_specific": {"severity": "CRITICAL"}}, {}) == "CRITICAL"
    assert dependency_audit._osv_severity({"id": "X"}, {"X": "9.8"}) == "CRITICAL"
    assert dependency_audit._osv_severity({"id": "X"}, {"X": "5.0"}) == "MEDIUM"
    assert dependency_audit._osv_severity({"id": "X"}, {}) == "HIGH"


# ---------------------------------------------------------------------------
# Scanner fail-closed behavior
# ---------------------------------------------------------------------------

def test_semgrep_timeout_is_a_high_finding_not_info(monkeypatch):
    # security_guard imports shutil inside the scanner, so the patch goes on the shutil module itself.
    monkeypatch.setattr(shutil, "which", lambda name: "semgrep")

    def timeout(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="semgrep", timeout=1)

    monkeypatch.setattr(security_guard.subprocess, "run", timeout)
    findings = security_guard.SemgrepScanner().scan_code("const x = 1;", file_name="sample.js")
    assert findings[0].severity == "HIGH"
    assert "did not complete" in findings[0].title


def test_semgrep_pack_is_chosen_by_language():
    assert security_guard.rules_for_file("a.py").endswith("semgrep_rules.yaml")
    assert security_guard.rules_for_file("a.ts").endswith("semgrep_rules_js.yaml")
    assert security_guard.rules_for_file("A.java").endswith("semgrep_rules_java.yaml")


# ---------------------------------------------------------------------------
# Compiler-backed Fact-Checker
# ---------------------------------------------------------------------------

@requires_tsc
def test_tsc_flags_hallucinated_javascript_api():
    findings = compiler_verifier.verify("const x = Math.sqroot(4);\n", "calc.js", "javascript")
    invalid = [f for f in findings if f["status"] == "INVALID"]
    assert invalid and invalid[0]["evidence"]["tool"] == "tsc"
    assert invalid[0]["title"] == "Non-existent API" and invalid[0]["line_number"] == 1


@requires_tsc
def test_tsc_accepts_valid_javascript():
    findings = compiler_verifier.verify("const path = require('path');\nmodule.exports = { j: (a, b) => path.join(a, b) };\n",
                                        "ok.js", "javascript")
    assert [f["status"] for f in findings] == ["VALID"]


@requires_tsc
def test_tsc_flags_wrong_typescript_member():
    findings = compiler_verifier.verify("const n: number = 3;\nconsole.log(n.toUpperCaseX());\n", "t.ts", "typescript")
    assert any(f["status"] == "INVALID" for f in findings)


@requires_javac
def test_javac_flags_hallucinated_java_api():
    code = "public class Calc {\n  static double root(double v) { return Math.sqroot(v); }\n}\n"
    findings = compiler_verifier.verify(code, "Calc.java", "java")
    invalid = [f for f in findings if f["status"] == "INVALID"]
    assert invalid and invalid[0]["evidence"]["tool"] == "javac"
    assert invalid[0]["line_number"] == 2


@requires_javac
def test_javac_accepts_valid_java():
    code = "public class Calc {\n  static double root(double v) { return Math.sqrt(v); }\n}\n"
    assert [f["status"] for f in compiler_verifier.verify(code, "Calc.java", "java")] == ["VALID"]


@requires_tsc
def test_fact_checker_uses_compiler_for_javascript():
    findings = FactCheckerAgent().analyze_code("const x = Math.sqroot(4);\n", file_path="calc.js", language="javascript")
    assert any(f.get("evidence", {}).get("tool") == "tsc" for f in findings)


# ---------------------------------------------------------------------------
# Semgrep packs for JavaScript and Java
# ---------------------------------------------------------------------------

def test_semgrep_javascript_pack_catches_command_injection_and_secret():
    code = (
        "const cp = require('child_process');\n"
        "function run(c) { cp.exec('ls ' + c); }\n"
        "const password = 'hunter2-production';\n"
    )
    rule_ids = {f["rule_id"] for f in run_security_scan(code, file_path="sample.js", run_llm_analysis=False)}
    assert any("js-command-injection" in r for r in rule_ids)
    assert any("js-hardcoded-secret" in r for r in rule_ids)


def test_semgrep_java_pack_catches_sql_injection_and_unsafe_deserialization():
    code = (
        "import java.sql.*;\n"
        "public class Repo {\n"
        "  void find(Statement s, String name) throws Exception {\n"
        "    s.executeQuery(\"SELECT * FROM users WHERE name = '\" + name + \"'\");\n"
        "  }\n"
        "  void load(java.io.InputStream in) throws Exception {\n"
        "    new java.io.ObjectInputStream(in).readObject();\n"
        "  }\n"
        "}\n"
    )
    rule_ids = {f["rule_id"] for f in run_security_scan(code, file_path="Repo.java", run_llm_analysis=False)}
    assert any("java-sql-string-concat" in r for r in rule_ids)
    assert any("java-unsafe-deserialization" in r for r in rule_ids)


# ---------------------------------------------------------------------------
# Maven dependency audit (osv-scanner)
# ---------------------------------------------------------------------------

@requires_osv
def test_osv_reports_known_vulnerable_maven_dependency(tmp_path):
    (tmp_path / "pom.xml").write_text(
        '<project xmlns="http://maven.apache.org/POM/4.0.0"><modelVersion>4.0.0</modelVersion>'
        "<groupId>x</groupId><artifactId>probe</artifactId><version>1</version><dependencies>"
        "<dependency><groupId>org.apache.logging.log4j</groupId><artifactId>log4j-core</artifactId>"
        "<version>2.14.1</version></dependency></dependencies></project>",
        encoding="utf-8",
    )
    findings = dependency_audit.audit_maven(str(tmp_path))
    assert findings, "expected known Log4j vulnerabilities for log4j-core 2.14.1"
    assert all(f["agent_name"] == "Purana-Saman" for f in findings)
    assert any(f["severity"] in ("CRITICAL", "HIGH") for f in findings)


def test_maven_audit_reports_missing_scanner(monkeypatch, tmp_path):
    monkeypatch.delenv("OSV_SCANNER_PATH", raising=False)
    monkeypatch.setattr(dependency_audit.shutil, "which", lambda name: None)
    findings = dependency_audit.audit_maven(str(tmp_path))
    assert findings[0]["status"] == "ERROR" and findings[0]["severity"] == "HIGH"


# ---------------------------------------------------------------------------
# Live sandbox runs for JavaScript and Java (need Docker and the sandbox image)
# ---------------------------------------------------------------------------

JS_CORRECT = "function add(a, b) { return a + b; }\nmodule.exports = { add };\n"
JS_WRONG = "function add(a, b) { return a * b; }\nmodule.exports = { add };\n"
JS_TEST = "const m = require('./calc');\ntest('add returns the sum', () => { expect(m.add(2, 3)).toBe(5); });\n"
JAVA_CORRECT = "public class Calc {\n  public static int add(int a, int b) { return a + b; }\n}\n"
JAVA_WRONG = "public class Calc {\n  public static int add(int a, int b) { return a * b; }\n}\n"
JAVA_TEST = (
    "import org.junit.jupiter.api.Test;\n"
    "import static org.junit.jupiter.api.Assertions.*;\n"
    "class CalcTest {\n  @Test void addsTwoNumbers() { assertEquals(5, Calc.add(2, 3)); }\n}\n"
)


@requires_sandbox
def test_live_jest_passes_correct_and_fails_wrong_javascript(monkeypatch):
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    executor = BlindTestExecutor(timeout_seconds=180)
    good = executor.execute_tests(JS_CORRECT, JS_TEST, module_name="calc", language="javascript")
    assert good["success"] is True and good["passed"] == 1
    bad = executor.execute_tests(JS_WRONG, JS_TEST, module_name="calc", language="javascript")
    assert bad["success"] is False
    assert any("AssertionError" in f["message"] for f in bad["failures"])


@requires_sandbox
def test_live_junit_passes_correct_and_fails_wrong_java(monkeypatch):
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    executor = BlindTestExecutor(timeout_seconds=180)
    good = executor.execute_tests(JAVA_CORRECT, JAVA_TEST, module_name="Calc", language="java")
    assert good["success"] is True and good["passed"] == 1
    bad = executor.execute_tests(JAVA_WRONG, JAVA_TEST, module_name="Calc", language="java")
    assert bad["success"] is False
    assert any("AssertionError" in f["message"] for f in bad["failures"])


@requires_sandbox
def test_live_java_compile_error_is_reported(monkeypatch):
    monkeypatch.setenv("SCEPTIC_SANDBOX", "docker")
    broken = "public class Calc {\n  public static int add(int a, int b) { return a + }\n}\n"
    result = BlindTestExecutor(timeout_seconds=180).execute_tests(broken, JAVA_TEST, module_name="Calc", language="java")
    assert result["success"] is False
    assert result["failures"][0]["test_name"] == "compilation"


def test_local_unsafe_refuses_non_python_languages(monkeypatch):
    monkeypatch.setenv("SCEPTIC_SANDBOX", "local-unsafe")
    result = BlindTestExecutor().execute_tests(JS_CORRECT, JS_TEST, module_name="calc", language="javascript")
    assert result["sandbox_unavailable"] is True
