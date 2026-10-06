import json
from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from security_guard import run_security_scan

@tool("Deterministic Security Guard Scanner")
def security_guard_tool(code_and_path_json: str) -> str:
    """
    Executes hybrid static analysis (Bandit, Semgrep) and contextual security assessment.
    Accepts a JSON string with keys:
    - 'source_code': str
    - 'file_path': Optional[str]
    Returns structured security findings.
    """
    try:
        data = json.loads(code_and_path_json)
        source_code = data["source_code"]
        file_path = data.get("file_path", "target.py")
        findings = run_security_scan(source_code, file_path=file_path)
        return json.dumps(findings, indent=2)
    except Exception as e:
        return json.dumps([{"agent_name": "Security-Guard", "severity": "HIGH", "error": str(e)}])

security_guard_agent = Agent(
    role="Security-Guard",
    goal="Analyze deterministic security scanner evidence and provide contextual security assessment.",
    backstory="You are an expert security verification agent. You combine static analysis results from Semgrep and Bandit with contextual intelligence to detect real vulnerabilities and explain their risks accurately.",
    tools=[security_guard_tool],
    verbose=True,
    allow_delegation=False
)

def analyze_with_security_guard(source_code: str, file_path: str = "target.py") -> str:
    payload = json.dumps({
        "source_code": source_code,
        "file_path": file_path
    })

    task = Task(
        description=f"Scan the target code for security vulnerabilities using your deterministic security tool with payload: {payload}. Return the structured security findings verbatim.",
        expected_output="A structured report of the security findings.",
        agent=security_guard_agent
    )

    crew = Crew(
        agents=[security_guard_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )

    result = crew.kickoff()
    return str(result)
