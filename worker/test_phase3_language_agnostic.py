"""
Comprehensive tests for Phase 3:
Language-Agnostic Code Analysis & Verification Foundation.
"""
import os
import sys
import pytest
from pathlib import Path

# Add paths
root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
worker_dir = os.path.join(root_dir, "worker")
for p in [root_dir, worker_dir]:
    if p not in sys.path:
        sys.path.insert(0, p)

from languages.detector import LanguageDetector
from languages.base import LanguageAdapterRegistry
from languages.universal_parser import UniversalParser
from languages.models import VerificationStatus
from fact_checker import analyze_code, FactCheckerAgent
from blind_tester import SpecificationMetadata
from security_guard import run_security_scan


# ========================================================
# 1. LANGUAGE DETECTION TESTS
# ========================================================

def test_language_detection_single_files():
    detector = LanguageDetector()
    assert detector.detect_file_language("app/main.py") == "python"
    assert detector.detect_file_language("src/App.java") == "java"
    assert detector.detect_file_language("index.js") == "javascript"
    assert detector.detect_file_language("component.jsx") == "javascript"
    assert detector.detect_file_language("types.ts") == "typescript"
    assert detector.detect_file_language("View.tsx") == "typescript"
    assert detector.detect_file_language("README.md") is None
    assert detector.detect_file_language("styles.css") is None


def test_language_detection_directory_and_mixed_repo(tmp_path):
    detector = LanguageDetector()

    # Create mixed directory
    (tmp_path / "backend").mkdir()
    (tmp_path / "frontend").mkdir()
    (tmp_path / "node_modules").mkdir()  # Ignored
    (tmp_path / ".git").mkdir()          # Ignored

    (tmp_path / "backend" / "server.py").write_text("print('server')", encoding="utf-8")
    (tmp_path / "backend" / "util.py").write_text("print('util')", encoding="utf-8")
    (tmp_path / "backend" / "Service.java").write_text("class Service {}", encoding="utf-8")
    (tmp_path / "frontend" / "app.ts").write_text("console.log('app')", encoding="utf-8")
    (tmp_path / "frontend" / "view.tsx").write_text("const X = 1;", encoding="utf-8")
    (tmp_path / "frontend" / "helper.js").write_text("function f(){}", encoding="utf-8")
    (tmp_path / "node_modules" / "leak.js").write_text("alert(1)", encoding="utf-8")

    result = detector.detect_languages(str(tmp_path))
    lang_names = [l["name"] for l in result["languages"]]
    assert "python" in lang_names
    assert "java" in lang_names
    assert "typescript" in lang_names
    assert "javascript" in lang_names
    assert result["total_files"] == 6  # Excludes node_modules


# ========================================================
# 2. ADAPTER SELECTION & REGISTRY TESTS
# ========================================================

def test_adapter_registry_discovery():
    assert "python" in LanguageAdapterRegistry.list_supported_languages()
    assert "java" in LanguageAdapterRegistry.list_supported_languages()
    assert "javascript" in LanguageAdapterRegistry.list_supported_languages()
    assert "typescript" in LanguageAdapterRegistry.list_supported_languages()

    py_adapter = LanguageAdapterRegistry.get_adapter("python")
    java_adapter = LanguageAdapterRegistry.get_adapter("java")
    js_adapter = LanguageAdapterRegistry.get_adapter("javascript")
    ts_adapter = LanguageAdapterRegistry.get_adapter("typescript")

    assert py_adapter.testing_framework == "pytest"
    assert java_adapter.testing_framework == "JUnit"
    assert js_adapter.testing_framework == "Jest"
    assert ts_adapter.testing_framework == "Jest"

    assert py_adapter.capabilities["api_verification"] is True
    assert java_adapter.capabilities["api_verification"] is True


# ========================================================
# 3. UNIVERSAL PARSER TESTS
# ========================================================

def test_universal_parser_python():
    code = """
import os

def calculate(x, y=10):
    \"\"\"Calculates sum.\"\"\"
    return os.path.join(str(x), str(y))

res = calculate(5)
"""
    parsed = UniversalParser.parse(code, "python", "calc.py")
    assert len(parsed.functions) == 1
    assert parsed.functions[0].name == "calculate"
    assert parsed.functions[0].docstring == "Calculates sum."
    assert len(parsed.calls) >= 1
    assert any(c.callee_name == "calculate" for c in parsed.calls)


def test_universal_parser_java():
    code = """
package com.example;
import java.util.Collections;

public class MathUtils {
    public int doubleValue(int n) {
        return n * 2;
    }
    public void execute() {
        doubleValue(4);
    }
}
"""
    parsed = UniversalParser.parse(code, "java", "MathUtils.java")
    assert len(parsed.classes) == 1
    assert parsed.classes[0].name == "MathUtils"
    assert len(parsed.functions) == 2
    func_names = [f.name for f in parsed.functions]
    assert "doubleValue" in func_names
    assert "execute" in func_names
    assert any(c.callee_name == "doubleValue" for c in parsed.calls)


def test_universal_parser_javascript():
    code = """
import { helper } from 'utils';

function renderUI(title) {
    console.log(title);
    return Math.abs(-10);
}
"""
    parsed = UniversalParser.parse(code, "javascript", "ui.js")
    assert len(parsed.functions) == 1
    assert parsed.functions[0].name == "renderUI"
    assert any(c.callee_name == "console.log" for c in parsed.calls)
    assert any(c.callee_name == "Math.abs" for c in parsed.calls)


def test_universal_parser_typescript():
    code = """
interface Config {
    debug: boolean;
}

export function startService(port: number): boolean {
    const valid = JSON.stringify({ port });
    return true;
}
"""
    parsed = UniversalParser.parse(code, "typescript", "service.ts")
    assert len(parsed.functions) == 1
    assert parsed.functions[0].name == "startService"
    assert any(c.callee_name == "JSON.stringify" for c in parsed.calls)


# ========================================================
# 4. FACT-CHECKER MULTI-LANGUAGE VERIFICATION
# ========================================================

def test_fact_checker_java_valid_api():
    java_code = """
public class Runner {
    public void run() {
        long t = System.currentTimeMillis();
        double val = Math.max(10.0, 20.0);
    }
}
"""
    findings = analyze_code(java_code, file_path="Runner.java")
    assert len(findings) == 2
    assert all(f["status"] == "VALID" for f in findings)
    assert all(f["evidence"]["language"] == "java" for f in findings)


def test_fact_checker_java_invalid_api():
    java_code = """
public class Runner {
    public void run() {
        System.nonExistentMethod();
    }
}
"""
    findings = analyze_code(java_code, file_path="Runner.java")
    assert len(findings) == 1
    assert findings[0]["status"] == "INVALID"
    assert findings[0]["title"] == "Non-existent API"
    assert "System" in findings[0]["evidence"]["class"]


def test_fact_checker_javascript_valid_api():
    js_code = """
function processData(val) {
    const res = Math.floor(val);
    const text = JSON.stringify({ res });
    return text;
}
"""
    findings = analyze_code(js_code, file_path="process.js")
    assert len(findings) == 2
    assert all(f["status"] == "VALID" for f in findings)
    assert all(f["evidence"]["language"] == "javascript" for f in findings)


def test_fact_checker_javascript_invalid_api():
    js_code = """
function processData() {
    Math.nonExistentMathOperation();
}
"""
    findings = analyze_code(js_code, file_path="process.js")
    assert len(findings) == 1
    assert findings[0]["status"] == "INVALID"
    assert findings[0]["title"] == "Non-existent API"


def test_fact_checker_typescript_unresolved_call():
    ts_code = """
function runService(client: any) {
    client.performCustomAction();
}
"""
    findings = analyze_code(ts_code, file_path="client.ts")
    assert len(findings) == 1
    assert findings[0]["status"] == "UNRESOLVED"
    assert "client" in findings[0]["evidence"]["target"]


def test_fact_checker_unsupported_language():
    findings = analyze_code("fn main() {}", file_path="main.rs", language="rust")
    assert len(findings) == 1
    assert findings[0]["status"] == "UNSUPPORTED"
    assert "rust" in findings[0]["title"].lower()


# ========================================================
# 5. BLIND TESTER & SECURITY GUARD LANGUAGE AWARENESS
# ========================================================

def test_blind_tester_specification_metadata_contains_language():
    spec = SpecificationMetadata(
        function_name="calculateTax",
        docstring="Computes tax for Java invoice.",
        specification="Must return double >= 0.",
        language="java",
        testing_framework="JUnit"
    )
    assert spec.language == "java"
    assert spec.testing_framework == "JUnit"
    # Strict isolation check still holds
    spec.validate_isolation()
    with pytest.raises(ValueError):
        spec.validate_isolation(extra_context={"source_code": "leak"})


def test_security_guard_scans_java_file_with_clean_findings():
    java_code = "public class SafeClass { public int add(int a, int b) { return a + b; } }"
    findings = run_security_scan(java_code, file_path="SafeClass.java", run_llm_analysis=False)
    assert len(findings) >= 1
    assert findings[0]["agent_name"] == "Security-Guard"
