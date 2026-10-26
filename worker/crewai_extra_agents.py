"""
Phase 2 agents as CrewAI agents: Leak-Hunter, Purana-Saman, and Jhooti-Docstring.

Each agent has one tool, served by the Sceptic MCP tool server. The verdicts come from the deterministic tools
(Gitleaks, pip-audit / npm audit) or from one constrained LLM call (docstring check).
"""
import json
from typing import Any, Dict, List

from crewai import Agent
from crewai.tools import tool

from mcp_client import get_mcp_client


@tool("Gitleaks Secret Scanner")
def leak_hunter_tool(path: str) -> str:
    """Scans a file or directory for committed secrets. Input: a path. Returns a JSON list of findings."""
    return get_mcp_client().call_tool("scan_secrets", {"path": path})


@tool("Dependency Vulnerability Auditor")
def purana_saman_tool(path: str) -> str:
    """Audits the dependency manifests next to a path (pip-audit, npm audit). Returns a JSON list of findings."""
    return get_mcp_client().call_tool("audit_dependencies", {"path": path})


@tool("Docstring Accuracy Judge")
def jhooti_docstring_tool(payload_json: str) -> str:
    """
    Checks docstrings against the code. Input: JSON with keys source_code and file_path.
    Returns a JSON list of findings.
    """
    try:
        data = json.loads(payload_json)
        return get_mcp_client().call_tool("judge_docstrings", {
            "source_code": data["source_code"],
            "file_path": data.get("file_path", "target.py"),
        })
    except Exception as e:
        return json.dumps([{"agent_name": "Jhooti-Docstring", "severity": "INFO", "status": "ERROR", "error": str(e)}])


leak_hunter_agent = Agent(
    role="Leak-Hunter",
    goal="Find committed secrets and credentials in the source tree and report them without revealing their values.",
    backstory="You scan repositories for leaked secrets using Gitleaks and report each finding with its location.",
    tools=[leak_hunter_tool],
    verbose=False,
    allow_delegation=False,
)

purana_saman_agent = Agent(
    role="Purana-Saman",
    goal="Find known vulnerabilities in the project's dependencies and report the fixed versions.",
    backstory="You audit dependency manifests with pip-audit and npm audit and report every known vulnerability.",
    tools=[purana_saman_tool],
    verbose=False,
    allow_delegation=False,
)

jhooti_docstring_agent = Agent(
    role="Jhooti-Docstring",
    goal="Check that docstrings describe what the functions do.",
    backstory="You compare each docstring with its implementation and flag documentation that is wrong.",
    tools=[jhooti_docstring_tool],
    verbose=False,
    allow_delegation=False,
)


def run_leak_hunter(path: str) -> List[Dict[str, Any]]:
    return json.loads(leak_hunter_tool.run(path))


def run_purana_saman(path: str) -> List[Dict[str, Any]]:
    return json.loads(purana_saman_tool.run(path))


def run_jhooti_docstring(source_code: str, file_path: str) -> List[Dict[str, Any]]:
    payload = json.dumps({"source_code": source_code, "file_path": file_path})
    return json.loads(jhooti_docstring_tool.run(payload))
