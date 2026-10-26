"""
Blind-Tester as a CrewAI agent.

The agent's tool is served by the Sceptic MCP tool server (run_blind_tests). Test generation sees only the
specification. The implementation is passed to the sandbox runner, never to the test generator.
"""
import json
from typing import Any, Dict, List

from crewai import Agent, Task, Crew, Process
from crewai.tools import tool

from mcp_client import get_mcp_client


@tool("Blind Specification Test Verifier")
def blind_test_verifier_tool(spec_and_code_json: str) -> str:
    """
    Executes independent specification-based test verification in the sandbox.
    Accepts a JSON string with keys:
    - 'function_name': str
    - 'docstring': str
    - 'specification': str
    - 'implementation_code': str
    - 'module_name': Optional[str]
    Returns structured test results comparing the implementation against independently generated tests.
    """
    try:
        data = json.loads(spec_and_code_json)
        args = {
            "function_name": data["function_name"],
            "docstring": data.get("docstring", ""),
            "specification": data.get("specification", ""),
            "implementation_code": data["implementation_code"],
            "module_name": data.get("module_name", "target_module"),
            "language": data.get("language", "python"),
        }
        return get_mcp_client().call_tool("run_blind_tests", args)
    except Exception as e:
        return json.dumps([{"agent_name": "Blind-Tester", "severity": "HIGH", "status": "ERROR", "error": str(e)}])


blind_tester_agent = Agent(
    role="Blind-Tester",
    goal=(
        "Generate independent specification-based tests without seeing the implementation and evaluate the "
        "target implementation through those tests."
    ),
    backstory=(
        "You are an independent specification-based testing agent. You do not see or rely on implementation "
        "details during test generation. You strictly evaluate whether the code meets its documented requirements."
    ),
    tools=[blind_test_verifier_tool],
    verbose=False,
    allow_delegation=False,
)


def run_blind_tester(
    function_name: str,
    docstring: str,
    specification: str,
    implementation_code: str,
    module_name: str = "target_module",
    language: str = "python",
) -> List[Dict[str, Any]]:
    """Runs the agent's tool for one function and returns its findings."""
    payload = json.dumps({
        "function_name": function_name,
        "docstring": docstring,
        "specification": specification,
        "implementation_code": implementation_code,
        "module_name": module_name,
        "language": language,
    })
    return json.loads(blind_test_verifier_tool.run(payload))


def analyze_with_blind_tester(
    function_name: str,
    docstring: str,
    specification: str,
    implementation_code: str
) -> str:
    """Full CrewAI run (requires an LLM). The pipeline itself uses run_blind_tester()."""
    payload = json.dumps({
        "function_name": function_name,
        "docstring": docstring,
        "specification": specification,
        "implementation_code": implementation_code,
    })
    task = Task(
        description=(
            "Evaluate the target function using your independent verification tool. "
            f"Pass the payload: {payload}. Return the exact structured findings."
        ),
        expected_output="A structured report of the specification testing findings.",
        agent=blind_tester_agent,
    )
    crew = Crew(agents=[blind_tester_agent], tasks=[task], process=Process.sequential, verbose=False)
    return str(crew.kickoff())
