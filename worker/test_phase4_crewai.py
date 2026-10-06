import os
import json
from dotenv import load_dotenv

load_dotenv()

def test_crewai_blind_tester_wrapper():
    from crewai_blind_tester import blind_tester_agent, blind_test_verifier_tool
    assert blind_tester_agent.role == "Blind-Tester"
    assert len(blind_tester_agent.tools) == 1

    # Test the tool execution directly
    payload = json.dumps({
        "function_name": "add",
        "docstring": "Adds two numbers",
        "specification": "Returns sum",
        "implementation_code": "def add(a, b): return a + b"
    })
    tool_output = blind_test_verifier_tool.run(payload)
    data = json.loads(tool_output)
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["agent_name"] == "Blind-Tester"

def test_crewai_security_guard_wrapper():
    from crewai_security_guard import security_guard_agent, security_guard_tool
    assert security_guard_agent.role == "Security-Guard"
    assert len(security_guard_agent.tools) == 1

    # Test the tool execution directly
    payload = json.dumps({
        "source_code": "def safe(): return 42",
        "file_path": "safe.py"
    })
    tool_output = security_guard_tool.run(payload)
    data = json.loads(tool_output)
    assert isinstance(data, list)
    assert len(data) > 0
    assert data[0]["agent_name"] == "Security-Guard"

if __name__ == "__main__":
    test_crewai_blind_tester_wrapper()
    print("CrewAI Blind-Tester wrapper test passed.")
    test_crewai_security_guard_wrapper()
    print("CrewAI Security-Guard wrapper test passed.")
