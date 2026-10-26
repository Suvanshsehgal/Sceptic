"""
Fact-Checker as a CrewAI agent.

The agent's only tool is served by the Sceptic MCP tool server (verify_api_usage). The verdict comes from the
deterministic tool, never from the LLM. analyze_with_crewai() runs a full Crew when an LLM is configured.
"""
import json
from typing import Any, Dict, List, Optional

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

from mcp_client import get_mcp_client


def _strip_code_fences(code: str) -> str:
    code = code.strip()
    if code.startswith("```python"):
        code = code[len("```python"):]
    elif code.startswith("```"):
        code = code[3:]
    if code.endswith("```"):
        code = code[:-3]
    return code.strip()


def _parse_tool_input(raw: str) -> Dict[str, Any]:
    """Accepts a JSON object {source_code, file_path, language} or plain Python source."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and "source_code" in data:
            return {
                "source_code": data["source_code"],
                "file_path": data.get("file_path", "target.py"),
                "language": data.get("language", "python"),
            }
    except (json.JSONDecodeError, TypeError):
        pass
    return {"source_code": _strip_code_fences(raw), "file_path": "target.py", "language": "python"}


@tool("Deterministic Python API Fact-Checker")
def deterministic_fact_checker(python_code: str) -> str:
    """
    Verifies whether the APIs, functions, and arguments used in the code exist in the installed environment.
    Input: Python source code, or a JSON object with keys source_code, file_path, language.
    Use this tool as the ground truth mechanism to verify API usage.
    """
    args = _parse_tool_input(python_code)
    return get_mcp_client().call_tool("verify_api_usage", args)


fact_checker_agent = Agent(
    role="Fact-Checker",
    goal="Verify API usage against the actual installed environment and report evidence-backed API findings.",
    backstory=(
        "You are an independent code verification agent. You do not guess API usage. You rely on the "
        "Deterministic Python API Fact-Checker tool to inspect the code and the installed environment, "
        "reporting exactly what the tool finds."
    ),
    tools=[deterministic_fact_checker],
    verbose=False,
    allow_delegation=False,
)


def run_fact_checker(source_code: str, file_path: str = "target.py", language: str = "python") -> List[Dict[str, Any]]:
    """Runs the agent's tool for one source file and returns its findings."""
    payload = json.dumps({"source_code": source_code, "file_path": file_path, "language": language or "python"})
    return json.loads(deterministic_fact_checker.run(payload))


def analyze_with_crewai(code: str) -> str:
    """Full CrewAI run (requires an LLM). The pipeline itself uses run_fact_checker()."""
    task = Task(
        description=(
            "Analyze the following Python code using your deterministic tool and return the structured findings "
            f"verbatim. Do not hallucinate findings. Code to check:\n\n```python\n{code}\n```"
        ),
        expected_output="A JSON-like structured report of the API findings exactly matching the tool's output.",
        agent=fact_checker_agent,
    )
    crew = Crew(agents=[fact_checker_agent], tasks=[task], process=Process.sequential, verbose=False)
    return str(crew.kickoff())
