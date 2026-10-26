"""
Security-Guard as a CrewAI agent.

The agent's tool is served by the Sceptic MCP tool server (scan_security): Semgrep and Bandit findings,
optionally triaged by Groq. The scanner evidence is kept even if the LLM step fails.
"""
import json
from typing import Any, Dict, List

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

from mcp_client import get_mcp_client


@tool("Deterministic Security Guard Scanner")
def security_guard_tool(code_and_path_json: str) -> str:
    """
    Executes hybrid static analysis (Bandit, Semgrep) and contextual security assessment.
    Accepts a JSON string with keys:
    - 'source_code': str
    - 'file_path': Optional[str]
    - 'run_llm_analysis': Optional[bool] (default true)
    Returns structured security findings.
    """
    try:
        data = json.loads(code_and_path_json)
        args = {
            "source_code": data["source_code"],
            "file_path": data.get("file_path", "target.py"),
            "run_llm_analysis": bool(data.get("run_llm_analysis", True)),
        }
        return get_mcp_client().call_tool("scan_security", args)
    except Exception as e:
        return json.dumps([{"agent_name": "Security-Guard", "severity": "HIGH", "status": "ERROR", "error": str(e)}])


security_guard_agent = Agent(
    role="Security-Guard",
    goal="Analyze deterministic security scanner evidence and provide a contextual security assessment.",
    backstory=(
        "You are an expert security verification agent. You combine static analysis results from Semgrep and "
        "Bandit with contextual intelligence to detect real vulnerabilities and explain their risks accurately."
    ),
    tools=[security_guard_tool],
    verbose=False,
    allow_delegation=False,
)


def run_security_guard(source_code: str, file_path: str = "target.py", run_llm_analysis: bool = True) -> List[Dict[str, Any]]:
    """Runs the agent's tool for one source file and returns its findings."""
    payload = json.dumps({
        "source_code": source_code,
        "file_path": file_path,
        "run_llm_analysis": run_llm_analysis,
    })
    return json.loads(security_guard_tool.run(payload))


def analyze_with_security_guard(source_code: str, file_path: str = "target.py") -> str:
    """Full CrewAI run (requires an LLM). The pipeline itself uses run_security_guard()."""
    payload = json.dumps({"source_code": source_code, "file_path": file_path})
    task = Task(
        description=(
            "Scan the target code for security vulnerabilities using your deterministic security tool with "
            f"payload: {payload}. Return the structured security findings verbatim."
        ),
        expected_output="A structured report of the security findings.",
        agent=security_guard_agent,
    )
    crew = Crew(agents=[security_guard_agent], tasks=[task], process=Process.sequential, verbose=False)
    return str(crew.kickoff())
