"""
Sceptic tool server (Model Context Protocol, stdio transport).

Every deterministic verification capability is exposed as an MCP tool. The CrewAI agents in
crewai_*.py call these tools through mcp_client.py, so the agents never import the scanners directly.

Run standalone with:  python -m mcp_server
Note: stdout carries the MCP protocol. Nothing in this process may print to stdout; logs go to stderr.
"""
import os
import re
import sys
import json
import logging

import httpx
from mcp.server.fastmcp import FastMCP

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from fact_checker import analyze_code
from blind_tester import SpecificationMetadata, run_blind_test
from security_guard import run_security_scan
import leak_hunter
import dependency_audit
import docstring_judge

logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("sceptic.mcp")

REPOSITORY_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")

mcp = FastMCP("sceptic-tools")


@mcp.tool()
def verify_api_usage(source_code: str, file_path: str = "target.py", language: str = "python") -> str:
    """Deterministically verify API calls and signatures in source code. Returns a JSON list of findings."""
    findings = analyze_code(source_code, file_path=file_path, language=language or None)
    return json.dumps(findings, indent=2)


@mcp.tool()
def scan_security(source_code: str, file_path: str = "target.py", run_llm_analysis: bool = True) -> str:
    """Run Semgrep and Bandit (plus optional Groq triage) on source code. Returns a JSON list of findings."""
    findings = run_security_scan(source_code, file_path=file_path, run_llm_analysis=run_llm_analysis)
    return json.dumps(findings, indent=2)


@mcp.tool()
def run_blind_tests(
    function_name: str,
    docstring: str,
    specification: str,
    implementation_code: str,
    module_name: str = "target_module",
    language: str = "python",
) -> str:
    """
    Generate specification-based tests without the implementation, then run them in the Blind-Tester sandbox.
    language: python, javascript, typescript, or java. Returns a JSON list of findings.
    """
    spec = SpecificationMetadata(
        function_name=function_name,
        docstring=docstring,
        specification=specification,
        module_name=module_name,
        language=language or "python",
    )
    findings = run_blind_test(spec, implementation_code, file_path=f"{module_name}.py")
    return json.dumps(findings, indent=2)


@mcp.tool()
def post_github_comment(repository: str, pr_number: int, body: str) -> str:
    """
    Post a summary comment on a GitHub pull request. Without GITHUB_TOKEN the call is a dry run and nothing is posted.
    """
    if not REPOSITORY_PATTERN.match(repository or ""):
        return json.dumps({"posted": False, "error": "repository must be in the form owner/name"})
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if not token:
        logger.info(f"post_github_comment dry run for {repository} PR #{pr_number} (GITHUB_TOKEN not set)")
        return json.dumps({"posted": False, "dry_run": True, "reason": "GITHUB_TOKEN not set"})

    url = f"https://api.github.com/repos/{repository}/issues/{int(pr_number)}/comments"
    try:
        resp = httpx.post(
            url,
            json={"body": body},
            headers={"Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json"},
            timeout=15.0,
        )
    except httpx.HTTPError as e:
        return json.dumps({"posted": False, "error": f"GitHub request failed: {e}"})
    return json.dumps({"posted": resp.status_code == 201, "status_code": resp.status_code, "dry_run": False})


@mcp.tool()
def scan_secrets(path: str) -> str:
    """Scan a file or directory for committed secrets with Gitleaks. Secret values are redacted. Returns JSON findings."""
    return json.dumps(leak_hunter.scan_secrets(path), indent=2)


@mcp.tool()
def audit_dependencies(path: str) -> str:
    """Audit requirements.txt (pip-audit) and package-lock.json (npm audit) next to a path. Returns JSON findings."""
    return json.dumps(dependency_audit.audit_dependencies(path), indent=2)


@mcp.tool()
def judge_docstrings(source_code: str, file_path: str = "target.py") -> str:
    """Check that each docstring describes its function, with one LLM call. Skipped when no Groq key is set."""
    return json.dumps(docstring_judge.judge_docstrings(source_code, file_path), indent=2)


if __name__ == "__main__":
    mcp.run()
