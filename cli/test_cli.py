import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock
from typer.testing import CliRunner
from cli.main import app, EXIT_SUCCESS, EXIT_AUDIT_FAILURE, EXIT_CLI_ERROR

runner = CliRunner()

@pytest.fixture
def sample_clean_code(tmp_path):
    f = tmp_path / "clean_sample.py"
    f.write_text(
        '"""Sample math module."""\n'
        'def add(a: int, b: int) -> int:\n'
        '    """Add two numbers together."""\n'
        '    return a + b\n'
    )
    return str(f)

@pytest.fixture
def sample_invalid_extension(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("Hello world")
    return str(f)


def test_cli_help():
    """Verify sceptic --help displays usage and available commands."""
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "Sceptic: Independent AI-Generated Code Verification System" in result.stdout
    assert "audit" in result.stdout


def test_cli_audit_help():
    """Verify sceptic audit --help displays audit command arguments and flags."""
    result = runner.invoke(app, ["audit", "--help"])
    assert result.exit_code == 0
    assert "Path to source file or directory to audit" in result.stdout
    assert "--verbose" in result.stdout
    assert "--json" in result.stdout


def test_cli_audit_nonexistent_path():
    """Verify audit returns EXIT_CLI_ERROR (2) when path does not exist."""
    result = runner.invoke(app, ["audit", "nonexistent/invalid_file.py"])
    assert result.exit_code == EXIT_CLI_ERROR
    assert "Path Error:" in result.stdout or "Path does not exist" in result.stdout


def test_cli_audit_invalid_file_extension(sample_invalid_extension):
    """Verify audit returns EXIT_CLI_ERROR (2) when file is not a supported source file."""
    result = runner.invoke(app, ["audit", sample_invalid_extension])
    assert result.exit_code == EXIT_CLI_ERROR
    assert "Validation Error:" in result.stdout or "Unsupported file type" in result.stdout


def test_cli_audit_empty_directory(tmp_path):
    """Verify audit returns EXIT_CLI_ERROR (2) when directory contains no supported files."""
    empty_dir = tmp_path / "empty_dir"
    empty_dir.mkdir()
    result = runner.invoke(app, ["audit", str(empty_dir)])
    assert result.exit_code == EXIT_CLI_ERROR
    assert "No supported source files found" in result.stdout


def test_cli_audit_approved_run(sample_clean_code):
    """Verify audit returns EXIT_SUCCESS (0) when trust score >= 85 and APPROVE."""
    mock_report = {
        "status": "COMPLETED",
        "trust_score": 92.5,
        "recommendation": "APPROVE",
        "summary": "Clean code with all verification checks passing.",
        "findings": [],
        "total_findings": 0,
        "severity_breakdown": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNRESOLVED": 0},
        "agent_statuses": {
            "Fact-Checker": "OK",
            "Blind-Tester": "OK",
            "Security-Guard": "OK",
            "Synthesizer": "OK"
        },
        "agent_contributions": {
            "Fact-Checker": 0,
            "Blind-Tester": 0,
            "Security-Guard": 0
        }
    }

    with patch("cli.main.AuditService.audit_path", return_value=mock_report):
        result = runner.invoke(app, ["audit", sample_clean_code])
        assert result.exit_code == EXIT_SUCCESS
        assert "TRUST SCORE: 92.5 / 100" in result.stdout
        assert "RECOMMENDATION: APPROVE" in result.stdout
        assert "Verification Agent Statuses" in result.stdout


def test_cli_audit_failure_run(sample_clean_code):
    """Verify audit returns EXIT_AUDIT_FAILURE (1) when critical findings or low score."""
    mock_report = {
        "status": "COMPLETED",
        "trust_score": 40.0,
        "recommendation": "BLOCK",
        "summary": "Vulnerabilities and hallucinated APIs detected.",
        "findings": [
            {
                "agent_name": "Security-Guard",
                "severity": "CRITICAL",
                "title": "Hardcoded AWS Secret",
                "file_path": sample_clean_code,
                "line_number": 4,
                "description": "Hardcoded credentials detected in source code.",
                "evidence": "AWS_SECRET = 'xyz'"
            }
        ],
        "total_findings": 1,
        "severity_breakdown": {"CRITICAL": 1, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNRESOLVED": 0},
        "agent_statuses": {
            "Fact-Checker": "OK",
            "Blind-Tester": "OK",
            "Security-Guard": "OK",
            "Synthesizer": "OK"
        },
        "agent_contributions": {
            "Fact-Checker": 0,
            "Blind-Tester": 0,
            "Security-Guard": 1
        }
    }

    with patch("cli.main.AuditService.audit_path", return_value=mock_report):
        result = runner.invoke(app, ["audit", sample_clean_code])
        assert result.exit_code == EXIT_AUDIT_FAILURE
        assert "TRUST SCORE: 40.0 / 100" in result.stdout
        assert "RECOMMENDATION: BLOCK" in result.stdout
        assert "Hardcoded" in result.stdout
        assert "Security-Guard" in result.stdout


def test_cli_audit_json_flag(sample_clean_code):
    """Verify --json produces valid JSON parseable report without Rich ANSI decorations."""
    mock_report = {
        "status": "COMPLETED",
        "trust_score": 90.0,
        "recommendation": "APPROVE",
        "summary": "OK",
        "findings": [],
        "total_findings": 0,
        "severity_breakdown": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 0, "LOW": 0, "UNRESOLVED": 0},
        "agent_statuses": {},
        "agent_contributions": {}
    }

    with patch("cli.main.AuditService.audit_path", return_value=mock_report):
        result = runner.invoke(app, ["audit", "--json", sample_clean_code])
        assert result.exit_code == EXIT_SUCCESS
        parsed = json.loads(result.stdout)
        assert parsed["trust_score"] == 90.0
        assert parsed["recommendation"] == "APPROVE"


def test_cli_audit_verbose_flag(sample_clean_code):
    """Verify --verbose displays evidence snippets for findings."""
    mock_report = {
        "status": "COMPLETED",
        "trust_score": 75.0,
        "recommendation": "REQUEST_CHANGES",
        "summary": "Medium findings detected.",
        "findings": [
            {
                "agent_name": "Fact-Checker",
                "severity": "MEDIUM",
                "title": "Non-existent argument",
                "file_path": sample_clean_code,
                "line_number": 2,
                "description": "Parameter 'foo' does not exist.",
                "evidence": "Call signature: func(foo=1)"
            }
        ],
        "total_findings": 1,
        "severity_breakdown": {"CRITICAL": 0, "HIGH": 0, "MEDIUM": 1, "LOW": 0, "UNRESOLVED": 0},
        "agent_statuses": {"Fact-Checker": "OK"},
        "agent_contributions": {"Fact-Checker": 1}
    }

    with patch("cli.main.AuditService.audit_path", return_value=mock_report):
        result = runner.invoke(app, ["audit", "-v", sample_clean_code])
        assert result.exit_code == EXIT_AUDIT_FAILURE
        assert "Finding Evidence Snippets" in result.stdout
        assert "Call signature: func(foo=1)" in result.stdout
