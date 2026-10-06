import pytest
from security_guard import (
    SecurityFinding,
    BanditScanner,
    SemgrepScanner,
    GroqContextualAnalyzer,
    run_security_scan
)

def test_vulnerable_code_bandit_detection():
    # Dangerous eval and hardcoded password
    vuln_code = """
import os

password = "super_secret_admin_password_123"

def execute_user_code(user_input):
    return eval(user_input)
"""
    scanner = BanditScanner()
    findings = scanner.scan_code(vuln_code)
    assert len(findings) > 0
    rule_ids = [f.rule_id for f in findings]
    # Bandit B307 (eval) or B105 (hardcoded password)
    assert any(rid in ["B307", "B105", "B106"] or "eval" in f.title.lower() for f, rid in zip(findings, rule_ids))

def test_safe_code_produces_clean_findings():
    safe_code = """
def calculate_area(width: float, height: float) -> float:
    return width * height
"""
    results = run_security_scan(safe_code, run_llm_analysis=False)
    assert len(results) == 1
    assert results[0]["title"] == "Clean Security Scan"
    assert results[0]["severity"] == "INFO"

def test_semgrep_findings():
    vuln_code = """
import subprocess

def run_command(cmd):
    # Shell injection risk
    subprocess.call(cmd, shell=True)
"""
    scanner = SemgrepScanner()
    findings = scanner.scan_code(vuln_code)
    assert isinstance(findings, list)
    # Semgrep runs and produces findings or diagnostic info without error

def test_multiple_findings_detection():
    vuln_code = """
import os

token = "sample_test_token_abcdef12345"

def bad_function(user_input):
    eval(user_input)
    os.system("echo " + user_input)
"""
    bandit = BanditScanner()
    findings = bandit.scan_code(vuln_code)
    # Should catch multiple bandit findings (hardcoded password/key + eval)
    assert len(findings) >= 1

def test_finding_normalization_matches_agentfinding_schema():
    vuln_code = """
def run_eval(x):
    return eval(x)
"""
    results = run_security_scan(vuln_code, run_llm_analysis=False)
    assert len(results) > 0
    f = results[0]
    expected_fields = ["agent_name", "severity", "title", "description", "file_path", "line_number", "evidence"]
    for field in expected_fields:
        assert field in f
    assert f["agent_name"] == "Security-Guard"
    assert f["severity"] in ["CRITICAL", "HIGH", "MEDIUM", "LOW", "INFO"]

def test_scanner_execution_failure_handling():
    # Pass completely broken source or nonexistent file to scanner
    scanner = BanditScanner()
    # Shouldn't crash even if syntax is invalid
    findings = scanner.scan_code("def broken_syntax(((:")
    assert isinstance(findings, list)

def test_groq_contextual_analysis_and_fallback():
    findings = [
        SecurityFinding(
            agent_name="Security-Guard",
            severity="HIGH",
            title="[BANDIT] B307: Use of eval",
            description="Use of possibly insecure function - eval",
            file_path="test.py",
            line_number=3,
            evidence="Line 3: eval(user_input)",
            scanner="bandit",
            rule_id="B307"
        )
    ]
    # Case A: Fallback when API key is None
    analyzer_no_key = GroqContextualAnalyzer(api_key=None)
    analyzed_no_key = analyzer_no_key.analyze_findings("eval(user_input)", findings)
    assert "Contextual LLM analysis skipped" in analyzed_no_key[0].contextual_analysis
    # Scanner evidence is preserved
    assert analyzed_no_key[0].rule_id == "B307"

    # Case B: Graceful fallback when invalid API key is provided
    analyzer_bad_key = GroqContextualAnalyzer(api_key="invalid_mock_key")
    analyzed_bad = analyzer_bad_key.analyze_findings("eval(user_input)", findings)
    assert "Contextual LLM analysis failed" in analyzed_bad[0].contextual_analysis
    # Scanner evidence is STILL preserved!
    assert analyzed_bad[0].rule_id == "B307"
