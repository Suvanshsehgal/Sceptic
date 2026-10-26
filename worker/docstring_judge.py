"""
Jhooti-Docstring: checks that docstrings describe what the code does.

One LLM call per file. The model receives the file and returns a verdict for each documented function.
A mismatch is a LOW finding, because wrong documentation is a quality problem, not a security or behavior problem.
Without GROQ_API_KEY the agent reports a skipped INFO finding, so the report shows that it did not run.
"""
import os
import re
import json
import logging
from typing import Any, Dict, List, Optional

from llm_client import make_groq_client, llm_blocked, note_llm_error

logger = logging.getLogger("sceptic.docstring_judge")

DEFAULT_MODEL = "openai/gpt-oss-120b"
MAX_SOURCE_CHARS = 20000


def _skipped(reason: str) -> Dict[str, Any]:
    return {
        "agent_name": "Jhooti-Docstring",
        "severity": "INFO",
        "status": "SKIPPED",
        "title": "Jhooti-Docstring skipped",
        "description": reason,
        "file_path": None,
        "line_number": None,
        "evidence": None,
        "recommendation": "Set GROQ_API_KEY to enable the docstring check.",
    }


PROMPT = (
    "You review Python docstrings. For each function below, decide whether its docstring accurately describes "
    "what the function does. Answer ONLY with JSON in this form: "
    '{"results": [{"function": "<name>", "verdict": "OK" or "MISMATCH", "reason": "<one sentence>"}]}. '
    "Only include functions that have a docstring. Do not invent functions."
)


def _parse_results(content: str) -> List[Dict[str, Any]]:
    content = content.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", content, re.S)
    if fenced:
        content = fenced.group(1)
    data = json.loads(content)
    results = data.get("results", []) if isinstance(data, dict) else []
    return [r for r in results if isinstance(r, dict) and r.get("function")]


def judge_docstrings(source_code: str, file_path: str, api_key: Optional[str] = None, model: Optional[str] = None) -> List[Dict[str, Any]]:
    key = (api_key if api_key is not None else os.getenv("GROQ_API_KEY", "")).strip()
    if not key:
        return [_skipped("GROQ_API_KEY is not set, so docstrings were not checked.")]
    if llm_blocked():
        return [_skipped("The daily Groq quota is reached, so docstrings were not checked.")]

    try:
        client = make_groq_client(key)
        response = client.chat.completions.create(
            model=model or os.getenv("GROQ_MODEL", DEFAULT_MODEL),
            messages=[
                {"role": "system", "content": PROMPT},
                {"role": "user", "content": f"File: {file_path}\n\n{source_code[:MAX_SOURCE_CHARS]}"},
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        results = _parse_results(response.choices[0].message.content or "")
    except Exception as e:
        logger.warning(f"Jhooti-Docstring LLM call failed: {type(e).__name__}")
        note_llm_error(e)
        return [{
            "agent_name": "Jhooti-Docstring",
            "severity": "INFO",
            "status": "ERROR",
            "title": "Jhooti-Docstring could not complete",
            "description": f"The docstring check failed: {type(e).__name__}",
            "file_path": file_path,
            "line_number": None,
            "evidence": None,
            "recommendation": "Re-run the audit, or check GROQ_API_KEY and GROQ_MODEL.",
        }]

    findings = []
    for item in results:
        if str(item.get("verdict", "")).upper() != "MISMATCH":
            continue
        findings.append({
            "agent_name": "Jhooti-Docstring",
            "severity": "LOW",
            "status": "OPEN",
            "title": f"Docstring does not match '{item.get('function')}'",
            "description": str(item.get("reason") or "The docstring describes different behavior.")[:500],
            "file_path": file_path,
            "line_number": None,
            "evidence": {"function": item.get("function")},
            "recommendation": "Update the docstring so it describes what the function actually does.",
        })
    return findings
