import pytest
from fact_checker import analyze_code

def test_valid_api():
    code = """
import os
os.path.join("a", "b")
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "VALID"
    assert findings[0]["title"] == "Valid API Usage"

def test_non_existent_function():
    code = """
import os
os.non_existent_function()
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "INVALID"
    assert findings[0]["title"] == "Non-existent API"

def test_invalid_keyword_parameter():
    code = """
import os
os.path.join("a", "b", invalid_param=True)
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "INVALID"
    assert findings[0]["title"] == "Invalid Keyword Parameter"

def test_missing_required_parameter():
    code = """
import json
json.loads()
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "INVALID"
    assert findings[0]["title"] == "Missing Required Parameter"

def test_valid_optional_parameter():
    code = """
import json
json.loads('{}', object_hook=None)
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "VALID"

def test_multiple_calls():
    code = """
import os
import json
os.path.join("a", "b")
os.path.join("a", "b", invalid_param=True)
"""
    findings = analyze_code(code)
    assert len(findings) == 2
    assert findings[0]["status"] == "VALID"
    assert findings[1]["status"] == "INVALID"
    assert findings[1]["line_number"] == 5

def test_unresolved_dynamic_call():
    code = """
obj.method()
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "UNRESOLVED"
    assert findings[0]["title"] == "Unresolved Dynamic Call"

def test_import_from_resolution():
    code = """
from os import path
path.join("a", "b")
"""
    findings = analyze_code(code)
    assert len(findings) == 1
    assert findings[0]["status"] == "VALID"
