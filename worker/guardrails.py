"""
Guardrails for Sceptic's agents (Phase C).

Three kinds of check, all deterministic and all fail-closed:

1. Input guards: untrusted text (questions, feature descriptions, docstrings, specs) is inspected before it reaches an
   LLM. A blocked text is never sent to the model. Checks: size, control characters, prompt-injection phrases and
   role-spoofing markers, and abusive language.
2. Tool output guards: a tool's return value must have the expected type and shape before an agent uses it. For the
   finding-producing tools that means a JSON list of well-formed findings. Anything else raises GuardViolation.
3. Callbacks for the frameworks: ADK model and tool callbacks (before/after) and a CrewAI step callback. They apply the
   checks above inside the framework's own execution loop and record every decision in an event log, so monitoring
   can see what was blocked and why.

The patterns are a heuristic first line, not a complete defence. Their measured block and false-block rates are in
evaluation/run_guardrail_eval.py, and that is the number to quote, not a claim of completeness.
"""
import json
import os
import re
import threading
import time
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

MAX_CHARS = {"question": 500, "feature": 4000, "docstring": 4000, "spec": 4000, "text": 4000}

# Phrases that try to override instructions or reveal the prompt.
_INJECTION = [
    re.compile(r"\b(ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|any|your|the)\b[^.\n]{0,20}\b(instructions?|prompts?|rules?|guidelines?|directives?|messages?)\b", re.I),
    re.compile(r"\b(reveal|print|show|repeat|leak|output)\b[^.\n]{0,30}\b(system|hidden|initial|original)\s+(prompt|instructions?|message)\b", re.I),
    re.compile(r"\byou\s+are\s+now\b|\bact\s+as\s+(an?\s+)?(unrestricted|unfiltered|jailbroken|dan\b)", re.I),
    # "developer mode" is only an injection when it is switched on. Mentioning it in documentation is not.
    re.compile(r"\b(enable|activate|switch\s+to|enter|turn\s+on|you\s+are\s+in)\s+(developer|dan)\s+mode\b|\bthis is a jailbreak\b|\bjailbreak\s+(prompt|attempt|me|the model)\b", re.I),
    re.compile(r"\b(pretend|imagine|assume)\b[^.\n]{0,30}\b(rules?|instructions?|guidelines?|restrictions?)\b[^.\n]{0,25}\b(do not|don'?t|doesn'?t|no longer|are void)\b", re.I),
    re.compile(r"<\|?(im_start|im_end|system|assistant|endoftext)\|?>|\[/?INST\]|<</?SYS>>", re.I),
    re.compile(r"^\s*#{2,}\s*(system|instructions?|new task)\b", re.I | re.M),
]

# Abusive or threatening language. Deliberately short: this is a floor, not a moderation model.
# A hyphen or word character next to the term means a compound name (for example "shit-list"), not the word itself.
_ABUSE = re.compile(
    r"(?<![-\w])(fuck(ing|er|ers)?|shit(ty)?|bitch(es)?|asshole|bastard|retard(ed)?|moron|dumbass|kill\s+yourself|kys)(?![-\w])",
    re.I,
)

_CONTROL = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


@dataclass
class GuardVerdict:
    kind: str
    allowed: bool
    reasons: List[str] = field(default_factory=list)
    checked_chars: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


PROMPT_GUARD_MODEL = "meta-llama/llama-prompt-guard-2-86m"
PROMPT_GUARD_THRESHOLD = float(os.getenv("SCEPTIC_PROMPT_GUARD_THRESHOLD", "0.5"))
_classifier_state = {"unavailable_reason": None}


_score_cache: Dict[str, float] = {}
_score_lock = threading.Lock()
SCORE_CACHE_MAX = 2000


def classify_injection(text: str) -> Optional[float]:
    """
    Second stage: Meta's Prompt Guard 2 (served by Groq) returns the probability that the text is a prompt-injection or
    jailbreak attempt. Returns None when no key is set or the call fails, so the regex stage still decides.
    Scores are cached by text, so a docstring repeated across an audit is classified once.
    """
    import hashlib
    cache_key = hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
    with _score_lock:
        if cache_key in _score_cache:
            _classifier_state["unavailable_reason"] = None
            return _score_cache[cache_key]
    score = _classify_remote(text)
    if score is not None:
        with _score_lock:
            if len(_score_cache) >= SCORE_CACHE_MAX:
                _score_cache.clear()
            _score_cache[cache_key] = score
    return score


def _classify_remote(text: str) -> Optional[float]:
    key = os.getenv("GROQ_API_KEY", "").strip()
    if not key:
        _classifier_state["unavailable_reason"] = "GROQ_API_KEY is not set"
        return None
    from llm_client import make_groq_client
    client = make_groq_client(key)
    last_error = None
    # A per-minute rate limit is retried a few times with a short wait. Other errors are not retried.
    for wait in (0, 3, 8, 15):
        if wait:
            time.sleep(wait)
        try:
            response = client.chat.completions.create(
                model=PROMPT_GUARD_MODEL,
                messages=[{"role": "user", "content": text[:4000]}],
                max_tokens=8,
                temperature=0,
            )
            score = float(response.choices[0].message.content.strip())
            _classifier_state["unavailable_reason"] = None
            return score
        except Exception as exc:  # the classifier is an extra layer: its failure must not block or pass silently
            last_error = exc
            if "429" not in str(exc) and "rate limit" not in str(exc).lower():
                break
    _classifier_state["unavailable_reason"] = f"{type(last_error).__name__}: {str(last_error)[:160]}"
    return None


def inspect_input(text: Any, kind: str = "text", use_classifier: bool = False) -> GuardVerdict:
    """
    Checks one piece of untrusted text. Never raises: a non-string is blocked with a reason.
    Stage 1 (always): size, control characters, injection patterns, abusive language.
    Stage 2 (use_classifier=True): Prompt Guard 2 score at or above SCEPTIC_PROMPT_GUARD_THRESHOLD.
    """
    if not isinstance(text, str):
        return GuardVerdict(kind, False, [f"expected text, got {type(text).__name__}"])
    reasons: List[str] = []
    limit = MAX_CHARS.get(kind, MAX_CHARS["text"])
    if len(text) > limit:
        reasons.append(f"too long: {len(text)} characters (limit {limit})")
    if _CONTROL.search(text):
        reasons.append("contains control characters")
    if any(p.search(text) for p in _INJECTION):
        reasons.append("prompt-injection pattern")
    if _ABUSE.search(text):
        reasons.append("abusive language")
    if use_classifier and not reasons:
        score = classify_injection(text)
        if score is not None and score >= PROMPT_GUARD_THRESHOLD:
            reasons.append(f"prompt-injection classifier score {score:.2f}")
    return GuardVerdict(kind, not reasons, reasons, len(text))


class GuardViolation(ValueError):
    """Raised when a tool output or input does not pass its guard. Callers treat it as an error, never as a pass."""


def validate_findings_json(text: str) -> List[Dict[str, Any]]:
    """
    A finding-producing tool must return a JSON list of objects. Each object must carry the common fields
    (agent_name, severity, title). Anything else raises GuardViolation.
    """
    from audit_models import validate_finding  # local import: keeps this module importable on its own

    try:
        data = json.loads(text)
    except (TypeError, ValueError) as exc:
        raise GuardViolation(f"tool output is not JSON: {exc}") from exc
    if not isinstance(data, list):
        raise GuardViolation(f"tool output is {type(data).__name__}, expected a list of findings")
    for index, item in enumerate(data):
        problems = validate_finding(item)
        if problems:
            raise GuardViolation(f"finding {index} is malformed: {'; '.join(problems)}")
    return data


# ---------------------------------------------------------------- event log (monitoring)

class GuardrailLog:
    """Thread-safe record of guard decisions. Entries hold the decision and reasons, never the checked text."""

    def __init__(self, limit: int = 1000):
        self._lock = threading.Lock()
        self._limit = limit
        self._events: List[Dict[str, Any]] = []

    def record(self, source: str, event: str, detail: str = "", **data: Any) -> None:
        entry = {"at": time.time(), "source": source, "event": event, "detail": detail[:300], **data}
        with self._lock:
            self._events.append(entry)
            if len(self._events) > self._limit:
                del self._events[: len(self._events) - self._limit]

    def events(self) -> List[Dict[str, Any]]:
        with self._lock:
            return list(self._events)

    def clear(self) -> None:
        with self._lock:
            self._events.clear()


LOG = GuardrailLog()


def check_and_log(text: Any, kind: str, source: str) -> GuardVerdict:
    """Runtime check: both stages. A classifier outage is logged, and the regex decision stands."""
    verdict = inspect_input(text, kind, use_classifier=True)
    if _classifier_state["unavailable_reason"]:
        LOG.record(source, "classifier_unavailable", _classifier_state["unavailable_reason"])
    if not verdict.allowed:
        LOG.record(source, "input_blocked", "; ".join(verdict.reasons), kind=kind)
    return verdict


# ---------------------------------------------------------------- framework callbacks

def _last_user_text(llm_request: Any) -> str:
    """The text of the newest user message in an ADK LlmRequest."""
    contents = getattr(llm_request, "contents", None) or []
    for content in reversed(contents):
        if getattr(content, "role", None) == "user":
            parts = getattr(content, "parts", None) or []
            return "".join(getattr(p, "text", "") or "" for p in parts)
    return ""


REFUSAL_TEXT = "This request was blocked by Sceptic's input guardrail, so no model answer was produced."


def adk_callbacks(source: str = "adk") -> Dict[str, Any]:
    """
    Callbacks for google.adk LlmAgent: before/after model and before/after tool.
    - before_model: inspects the newest user text; a blocked request returns a refusal and the model is not called.
    - after_model: records the model call (no text).
    - before_tool: rejects tool arguments that are not plain strings or numbers.
    - after_tool: rejects a tool return that is neither a dict nor a string, and replaces it with an error dict.
    """
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    def before_model(callback_context, llm_request):
        verdict = check_and_log(_last_user_text(llm_request), "question", f"{source}.model")
        if verdict.allowed:
            LOG.record(source, "model_call", "allowed")
            return None
        return LlmResponse(content=types.Content(role="model", parts=[types.Part(text=REFUSAL_TEXT)]))

    def after_model(callback_context, llm_response):
        LOG.record(source, "model_response", "received")
        return None

    def before_tool(tool, args, tool_context):
        bad = [k for k, v in (args or {}).items() if not isinstance(v, (str, int, float, bool, type(None)))]
        if bad:
            LOG.record(source, "tool_blocked", f"non-scalar arguments: {', '.join(bad)}", tool=tool.name)
            return {"error": f"arguments {', '.join(bad)} must be plain values"}
        return None

    def after_tool(tool, args, tool_context, tool_response):
        if isinstance(tool_response, (dict, str)):
            return None
        LOG.record(source, "tool_output_blocked", f"returned {type(tool_response).__name__}", tool=tool.name)
        return {"error": f"tool returned {type(tool_response).__name__}; expected an object or text"}

    return {
        "before_model_callback": before_model,
        "after_model_callback": after_model,
        "before_tool_callback": before_tool,
        "after_tool_callback": after_tool,
    }


def crewai_step_callback(source: str = "crewai"):
    """Returns a CrewAI step_callback that records each agent step (its type and size, not its content)."""
    def step(step_output: Any) -> None:
        text = str(getattr(step_output, "text", "") or step_output or "")
        LOG.record(source, "agent_step", f"{len(text)} chars")
    return step
