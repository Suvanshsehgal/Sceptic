import json
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from blind_tester import SpecificationMetadata, run_blind_test

@tool("Blind Specification Test Verifier")
def blind_test_verifier_tool(spec_and_code_json: str) -> str:
    """
    Executes independent specification-based test verification.
    Accepts a JSON string with keys:
    - 'function_name': str
    - 'docstring': str
    - 'specification': str
    - 'implementation_code': str
    Returns structured test results comparing the implementation against independently generated tests.
    """
    try:
        data = json.loads(spec_and_code_json)
        spec = SpecificationMetadata(
            function_name=data["function_name"],
            docstring=data.get("docstring", ""),
            specification=data.get("specification", "")
        )
        impl_code = data["implementation_code"]
        findings = run_blind_test(spec, impl_code)
        return json.dumps(findings, indent=2)
    except Exception as e:
        return json.dumps([{"agent_name": "Blind-Tester", "severity": "HIGH", "status": "FAIL", "error": str(e)}])

blind_tester_agent = Agent(
    role="Blind-Tester",
    goal="Generate independent specification-based tests without seeing the implementation and evaluate the target implementation through those tests.",
    backstory="You are an independent specification-based testing agent. You do not see or rely on implementation details during test generation. You strictly evaluate whether the code meets its documented requirements.",
    tools=[blind_test_verifier_tool],
    verbose=True,
    allow_delegation=False
)

def analyze_with_blind_tester(
    function_name: str,
    docstring: str,
    specification: str,
    implementation_code: str
) -> str:
    payload = json.dumps({
        "function_name": function_name,
        "docstring": docstring,
        "specification": specification,
        "implementation_code": implementation_code
    })

    task = Task(
        description=f"Evaluate the target function using your independent verification tool. Pass the payload: {payload}. Return the exact structured findings.",
        expected_output="A structured report of the specification testing findings.",
        agent=blind_tester_agent
    )

    crew = Crew(
        agents=[blind_tester_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    result = crew.kickoff()
    return str(result)
