from crewai import Agent, Task, Crew, Process
from crewai.tools import tool
from fact_checker import analyze_code
import json

@tool("Deterministic Python API Fact-Checker")
def deterministic_fact_checker(python_code: str) -> str:
    """
    Analyzes Python source code deterministically to verify if the APIs,
    functions, and arguments used actually exist in the installed environment.
    Use this tool as the ground truth mechanism to verify API usage.
    """
    # Remove markdown code blocks if the LLM passes them
    if python_code.startswith("```python"):
        python_code = python_code[9:]
    if python_code.startswith("```"):
        python_code = python_code[3:]
    if python_code.endswith("```"):
        python_code = python_code[:-3]
        
    findings = analyze_code(python_code)
    return json.dumps(findings, indent=2)

fact_checker_agent = Agent(
    role="Fact-Checker",
    goal="Verify Python API usage against the actual installed environment and report evidence-backed API findings.",
    backstory="You are an independent code verification agent. You do not guess API usage. You strictly rely on the Deterministic Python API Fact-Checker tool to inspect the AST and the installed environment, reporting exactly what the tool finds.",
    tools=[deterministic_fact_checker],
    verbose=True,
    allow_delegation=False
)

def analyze_with_crewai(code: str) -> str:
    task = Task(
        description=f"Analyze the following Python code using your deterministic tool and return the structured findings verbatim. Do not hallucinate findings. Code to check:\n\n```python\n{code}\n```",
        expected_output="A JSON-like structured report of the API findings exactly matching the tool's output.",
        agent=fact_checker_agent
    )
    
    crew = Crew(
        agents=[fact_checker_agent],
        tasks=[task],
        process=Process.sequential,
        verbose=True
    )
    
    result = crew.kickoff()
    return str(result)
