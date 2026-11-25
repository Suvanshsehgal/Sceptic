"""
Tracing for Sceptic: auditability and provenance in Langfuse (over OpenTelemetry).

Design rules
- Optional. Without LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY (or with SCEPTIC_TRACING=off) every function here is
  a cheap no-op and nothing is sent anywhere.
- Fail-safe. A tracing error is logged and swallowed. It must never change an audit result or raise into the pipeline.
- No code or prompt text leaves the process by default. Spans carry sizes, hashes, counts and verdicts. Set
  SCEPTIC_TRACE_CONTENT=true to also send (clipped, secret-masked) source, prompts and responses, which is
  appropriate for a self-hosted Langfuse.
- One trace per audit. Agent spans, MCP tool calls and LLM generations are nested under it, including the tool
  calls that run in the MCP server subprocess (the trace context travels as a tool argument).

Environment
  LANGFUSE_PUBLIC_KEY / LANGFUSE_SECRET_KEY   credentials (both required to enable tracing)
  LANGFUSE_HOST (or LANGFUSE_BASE_URL)         default https://cloud.langfuse.com
  LANGFUSE_PUBLIC_URL                          browser-facing base URL for trace links (defaults to the host)
  SCEPTIC_TRACING=off                          disable tracing even when keys are set
  SCEPTIC_TRACE_CONTENT=true                   include clipped, masked content in spans
  SCEPTIC_LLM_PRICE_INPUT_PER_1M / _OUTPUT_PER_1M   USD per million tokens, to attach cost to LLM generations
"""
import contextlib
import functools
import hashlib
import json
import logging
import os
import re
import threading
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger("sceptic.tracing")

_lock = threading.Lock()
_client: Any = None
_initialized = False
_instrumented: set = set()

CONTENT_CLIP_CHARS = 4000


# ---------------------------------------------------------------- configuration

def _flag(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    return value.strip().lower() in ("1", "true", "yes", "on")


def configured() -> bool:
    """True when credentials are present and tracing has not been switched off."""
    if os.getenv("SCEPTIC_TRACING", "").strip().lower() in ("off", "false", "0", "no"):
        return False
    return bool(os.getenv("LANGFUSE_PUBLIC_KEY", "").strip() and os.getenv("LANGFUSE_SECRET_KEY", "").strip())


def content_enabled() -> bool:
    """True when prompts, responses and source may be attached to spans (clipped and secret-masked)."""
    return _flag("SCEPTIC_TRACE_CONTENT", False)


def _environment_name() -> Optional[str]:
    raw = os.getenv("ENVIRONMENT", "").strip().lower()
    cleaned = re.sub(r"[^a-z0-9_-]", "-", raw)
    return cleaned if cleaned and not cleaned.startswith("langfuse") else None


# ---------------------------------------------------------------- masking

_SECRET_PATTERNS = [
    re.compile(r"gsk_[A-Za-z0-9]{20,}"),
    re.compile(r"sk-[A-Za-z0-9_\-]{20,}"),
    re.compile(r"AKIA[0-9A-Z]{16}"),
    re.compile(r"gh[pousr]_[A-Za-z0-9]{30,}"),
    re.compile(r"eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}"),
]
_ASSIGNED_SECRET = re.compile(
    r"""(?i)\b(password|passwd|pwd|secret|api[_-]?key|token)(\s*[:=]\s*)(['"])[^'"\s]{4,}\3"""
)
REDACTED = "[REDACTED]"


def mask_text(text: str) -> str:
    """Replaces common credential shapes. Best effort: the default is not to send content at all."""
    for pattern in _SECRET_PATTERNS:
        text = pattern.sub(REDACTED, text)
    return _ASSIGNED_SECRET.sub(lambda m: f"{m.group(1)}{m.group(2)}{m.group(3)}{REDACTED}{m.group(3)}", text)


def mask_data(data: Any) -> Any:
    """Langfuse mask function: applied to every input, output and metadata value before export."""
    if isinstance(data, str):
        return mask_text(data)
    if isinstance(data, dict):
        return {key: mask_data(value) for key, value in data.items()}
    if isinstance(data, (list, tuple)):
        return [mask_data(item) for item in data]
    return data


def _langfuse_mask(*, data: Any, **_: Any) -> Any:
    return mask_data(data)


# ---------------------------------------------------------------- client lifecycle

class _Obs:
    """Wraps a Langfuse observation so that no tracing call can raise into the caller."""

    def __init__(self, inner: Any = None):
        self._inner = inner

    @property
    def trace_id(self) -> Optional[str]:
        return getattr(self._inner, "trace_id", None) if self._inner is not None else None

    @property
    def id(self) -> Optional[str]:
        return getattr(self._inner, "id", None) if self._inner is not None else None

    def update(self, **kwargs: Any) -> None:
        if self._inner is None:
            return
        try:
            self._inner.update(**{k: v for k, v in kwargs.items() if v is not None})
        except Exception as exc:
            logger.debug(f"tracing update failed: {exc}")

    def fail(self, message: str) -> None:
        self.update(level="ERROR", status_message=str(message)[:500])

    def warn(self, message: str) -> None:
        self.update(level="WARNING", status_message=str(message)[:500])


_NOOP = _Obs()


def _create_client() -> Any:
    from langfuse import Langfuse

    return Langfuse(
        public_key=os.getenv("LANGFUSE_PUBLIC_KEY", "").strip(),
        secret_key=os.getenv("LANGFUSE_SECRET_KEY", "").strip(),
        host=(os.getenv("LANGFUSE_BASE_URL") or os.getenv("LANGFUSE_HOST") or "").strip() or None,
        environment=_environment_name(),
        release=os.getenv("COMMIT_SHA") or None,
        flush_interval=float(os.getenv("SCEPTIC_TRACE_FLUSH_SECONDS", "2")),
        mask=_langfuse_mask,
    )


def _get_client() -> Any:
    """The Langfuse client, created on first use. None when tracing is off or could not start."""
    global _client, _initialized
    if _initialized:
        return _client
    with _lock:
        if _initialized:
            return _client
        if configured():
            try:
                _client = _create_client()
                logger.info("Tracing enabled (Langfuse).")
            except Exception as exc:
                _client = None
                logger.warning(f"Tracing disabled: Langfuse client could not start: {exc}")
        _initialized = True
        return _client


def enabled() -> bool:
    return _get_client() is not None


def configure(client: Any) -> None:
    """Install a client directly (tests, or an application that builds its own Langfuse client)."""
    global _client, _initialized
    with _lock:
        _client = client
        _initialized = True


def reset() -> None:
    """Forget the client so the next call re-reads the environment."""
    global _client, _initialized
    with _lock:
        _client = None
        _initialized = False
        _instrumented.clear()


def flush() -> None:
    client = _client
    if client is None:
        return
    try:
        client.flush()
    except Exception as exc:
        logger.debug(f"tracing flush failed: {exc}")


def shutdown() -> None:
    """Flush and stop the exporter. Call before a short-lived process exits."""
    client = _client
    if client is None:
        return
    try:
        client.shutdown()
    except Exception as exc:
        logger.debug(f"tracing shutdown failed: {exc}")


def instrument_frameworks(frameworks: tuple = ("crewai",)) -> List[str]:
    """
    Turns on the OpenInference instrumentors so framework spans (CrewAI crews and tasks, ADK runs, agents, tools
    and model calls) appear in the same trace. Returns the frameworks that were instrumented. Never raises.
    """
    # Framework instrumentors record full tool inputs and LLM prompts (CrewAI tool spans contain the whole source).
    # They are therefore only turned on in content mode, the same opt-in that allows source into our own spans.
    if not enabled() or not content_enabled() or not _flag("SCEPTIC_TRACE_FRAMEWORKS", True):
        return []
    done: List[str] = []
    for name in frameworks:
        if name in _instrumented:
            done.append(name)
            continue
        try:
            if name == "crewai":
                from openinference.instrumentation.crewai import CrewAIInstrumentor as instrumentor
            elif name == "google_adk":
                from openinference.instrumentation.google_adk import GoogleADKInstrumentor as instrumentor
            else:
                continue
            instrumentor().instrument()
            _instrumented.add(name)
            done.append(name)
        except Exception as exc:
            logger.warning(f"Could not instrument {name}: {exc}")
    return done


# ---------------------------------------------------------------- spans

@contextlib.contextmanager
def observation(
    name: str,
    *,
    as_type: str = "span",
    input: Any = None,
    metadata: Optional[Dict[str, Any]] = None,
    trace_context: Optional[Dict[str, str]] = None,
    **kwargs: Any,
) -> Iterator[_Obs]:
    """
    A span (or agent, tool, generation, ...) that is a child of the current span. An exception that leaves the
    block marks the span as an error and is re-raised unchanged.
    """
    client = _get_client()
    if client is None:
        yield _NOOP
        return
    try:
        manager = client.start_as_current_observation(
            name=name, as_type=as_type, input=input, metadata=metadata, trace_context=trace_context, **kwargs
        )
        inner = manager.__enter__()
    except Exception as exc:
        logger.debug(f"tracing could not start '{name}': {exc}")
        yield _NOOP
        return

    obs = _Obs(inner)
    try:
        yield obs
    except BaseException as exc:
        obs.fail(f"{type(exc).__name__}: {exc}")
        try:
            manager.__exit__(type(exc), exc, exc.__traceback__)
        except Exception:
            pass
        raise
    else:
        try:
            manager.__exit__(None, None, None)
        except Exception as exc:
            logger.debug(f"tracing could not end '{name}': {exc}")


def _has_active_span() -> bool:
    try:
        from opentelemetry import trace as otel_trace

        return otel_trace.get_current_span().get_span_context().is_valid
    except Exception:
        return False


@contextlib.contextmanager
def trace(
    name: str,
    *,
    input: Any = None,
    session_id: Optional[str] = None,
    tags: Optional[List[str]] = None,
    metadata: Optional[Dict[str, Any]] = None,
    as_type: str = "span",
) -> Iterator[_Obs]:
    """
    The root of one logical run (an audit, a watchdog check). When a span is already active the run nests under it,
    so a caller that opened a trace keeps one trace. trace_id on the yielded object identifies the trace.
    """
    client = _get_client()
    if client is None:
        yield _NOOP
        return

    meta = {str(k): str(v)[:200] for k, v in (metadata or {}).items() if v is not None}
    with contextlib.ExitStack() as stack:
        if not _has_active_span():
            try:
                from langfuse import propagate_attributes

                stack.enter_context(propagate_attributes(
                    trace_name=name, session_id=(session_id or None), tags=tags or None, metadata=meta or None,
                ))
            except Exception as exc:
                logger.debug(f"tracing could not set trace attributes: {exc}")
        with observation(name, as_type=as_type, input=input, metadata=meta or None) as obs:
            yield obs


def current_trace_context() -> Optional[Dict[str, str]]:
    """Identifies the active span so another process can attach its spans to it."""
    client = _get_client()
    if client is None:
        return None
    try:
        trace_id = client.get_current_trace_id()
        span_id = client.get_current_observation_id()
    except Exception:
        return None
    if not trace_id or not span_id:
        return None
    return {"trace_id": trace_id, "parent_span_id": span_id}


_HEX32 = re.compile(r"^[0-9a-f]{32}$")
_HEX16 = re.compile(r"^[0-9a-f]{16}$")


def encode_context(context: Optional[Dict[str, str]]) -> str:
    return json.dumps(context) if context else ""


def decode_context(raw: str) -> Optional[Dict[str, str]]:
    """Parses a trace context received as a tool argument. Anything malformed is ignored, not trusted."""
    if not raw:
        return None
    try:
        data = json.loads(raw)
        trace_id, parent = str(data["trace_id"]), str(data["parent_span_id"])
    except Exception:
        return None
    if _HEX32.match(trace_id) and _HEX16.match(parent):
        return {"trace_id": trace_id, "parent_span_id": parent}
    return None


def wrap_context(fn):
    """
    Returns fn bound to the caller's current trace context, for work handed to another thread (a thread pool does
    not inherit it). Safe to call the result from several threads at once.
    """
    try:
        from opentelemetry import context as otel_context

        captured = otel_context.get_current()
    except Exception:
        return fn

    @functools.wraps(fn)
    def runner(*args, **kwargs):
        token = otel_context.attach(captured)
        try:
            return fn(*args, **kwargs)
        finally:
            otel_context.detach(token)

    return runner


def trace_url(trace_id: Optional[str]) -> Optional[str]:
    """A link a browser can open. Built from the host, with no network call. None when tracing is not configured."""
    if not trace_id or not configured():
        return None
    base = (os.getenv("LANGFUSE_PUBLIC_URL") or os.getenv("LANGFUSE_BASE_URL")
            or os.getenv("LANGFUSE_HOST") or "https://cloud.langfuse.com").strip().rstrip("/")
    return f"{base}/trace/{trace_id}"


# ---------------------------------------------------------------- what goes into spans

def clip(text: Any, limit: int = CONTENT_CLIP_CHARS) -> str:
    text = text if isinstance(text, str) else json.dumps(text, default=str)
    return text if len(text) <= limit else text[:limit] + f"... [{len(text) - limit} more chars]"


def digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()[:12]


def describe_text(text: Optional[str], key: str = "text") -> Dict[str, Any]:
    """Size and hash of a text. Includes the clipped text only when content tracing is on."""
    text = text or ""
    info: Dict[str, Any] = {f"{key}_chars": len(text), f"{key}_sha256": digest(text)}
    if content_enabled():
        info[key] = clip(text)
    return info


def severity_counts(findings: List[Dict[str, Any]]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for finding in findings:
        if isinstance(finding, dict):
            severity = str(finding.get("severity") or "INFO").upper()
            counts[severity] = counts.get(severity, 0) + 1
    return counts


def summarize_findings(findings: Any) -> Dict[str, Any]:
    """Counts only: how many findings, by severity, and how many are errors. No finding text."""
    if not isinstance(findings, list):
        return {"findings": 0}
    errors = sum(1 for f in findings if isinstance(f, dict) and str(f.get("status") or "").upper() == "ERROR")
    return {"findings": len(findings), "severities": severity_counts(findings), "errors": errors}


def summarize_tool_output(text: str) -> Dict[str, Any]:
    try:
        data = json.loads(text)
    except Exception:
        return describe_text(text, "output")
    if isinstance(data, list):
        summary = summarize_findings(data)
    elif isinstance(data, dict):
        summary = {key: data[key] for key in ("posted", "dry_run", "status_code") if key in data}
        summary["keys"] = sorted(str(k) for k in data)[:12]
    else:
        summary = {}
    if content_enabled():
        summary["output"] = clip(text)
    return summary


_SAFE_ARGUMENT_KEYS = frozenset({
    "language", "function_name", "module_name", "run_llm_analysis", "repository", "pr_number",
})
_PATH_ARGUMENT_KEYS = frozenset({"file_path", "path"})


def short_path(path: Any, keep: int = 3) -> str:
    """The last few components of a path, so a home directory or user name is not exported."""
    parts = re.split(r"[\\/]+", str(path).strip())
    parts = [p for p in parts if p]
    return "/".join(parts[-keep:]) if parts else ""


def summarize_tool_input(arguments: Dict[str, Any]) -> Dict[str, Any]:
    """
    What is recorded about a tool call's arguments. Only names known to be safe (language, function name, ...) are
    kept as they are and paths are shortened. Everything else, in particular source code, docstrings and comment
    bodies, is reduced to its size and hash, whatever its length. Content is added only in content mode.
    """
    summary: Dict[str, Any] = {}
    for key, value in arguments.items():
        if key == "trace_context":
            continue
        if key in _SAFE_ARGUMENT_KEYS and isinstance(value, (str, int, float, bool)) and len(str(value)) <= 200:
            summary[key] = value
        elif key in _PATH_ARGUMENT_KEYS and isinstance(value, str):
            summary[key] = short_path(value)
        elif isinstance(value, str):
            summary.update(describe_text(value, key))
        else:
            summary[key] = type(value).__name__
    return summary


# ---------------------------------------------------------------- LLM generations

def _price(name: str) -> Optional[float]:
    try:
        return float(os.environ[name])
    except (KeyError, ValueError):
        return None


def llm_cost(input_tokens: int, output_tokens: int) -> Optional[Dict[str, float]]:
    """USD cost from SCEPTIC_LLM_PRICE_INPUT_PER_1M and SCEPTIC_LLM_PRICE_OUTPUT_PER_1M. None when not configured."""
    price_in = _price("SCEPTIC_LLM_PRICE_INPUT_PER_1M")
    price_out = _price("SCEPTIC_LLM_PRICE_OUTPUT_PER_1M")
    if price_in is None or price_out is None:
        return None
    cost_in = input_tokens * price_in / 1_000_000
    cost_out = output_tokens * price_out / 1_000_000
    return {"input": cost_in, "output": cost_out, "total": cost_in + cost_out}


def _messages_input(messages: Any) -> Dict[str, Any]:
    if not isinstance(messages, list):
        return {"messages": 0}
    total = sum(len(str(m.get("content", ""))) for m in messages if isinstance(m, dict))
    info: Dict[str, Any] = {
        "messages": len(messages),
        "roles": [m.get("role") for m in messages if isinstance(m, dict)],
        "prompt_chars": total,
        "prompt_sha256": digest(json.dumps(messages, default=str)),
    }
    if content_enabled():
        info["content"] = [
            {"role": m.get("role"), "content": clip(str(m.get("content", "")))}
            for m in messages if isinstance(m, dict)
        ]
    return info


def _response_output(response: Any) -> Dict[str, Any]:
    try:
        text = response.choices[0].message.content or ""
        finish = response.choices[0].finish_reason
    except Exception:
        return {}
    info: Dict[str, Any] = {"response_chars": len(text), "finish_reason": finish}
    if content_enabled():
        info["content"] = clip(text)
    return info


def _usage(response: Any) -> Dict[str, int]:
    usage = getattr(response, "usage", None)
    prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
    completion = int(getattr(usage, "completion_tokens", 0) or 0)
    total = int(getattr(usage, "total_tokens", 0) or 0) or prompt + completion
    return {"input": prompt, "output": completion, "total": total}


def wrap_groq_client(client: Any) -> Any:
    """
    Records every chat completion as a Langfuse generation: model, parameters, token usage, optional cost, latency
    and errors. The client is returned unchanged when tracing is off, so there is no overhead and no behaviour change.
    """
    if not enabled():
        return client
    try:
        completions = client.chat.completions
        original = completions.create
    except Exception:
        return client

    @functools.wraps(original)
    def traced_create(*args, **kwargs):
        params = {k: kwargs[k] for k in ("temperature", "max_tokens", "top_p", "max_completion_tokens") if k in kwargs}
        with observation(
            "groq.chat.completions",
            as_type="generation",
            model=str(kwargs.get("model") or "unknown"),
            model_parameters={k: v for k, v in params.items() if isinstance(v, (int, float, str, bool))} or None,
            input=_messages_input(kwargs.get("messages")),
        ) as generation:
            response = original(*args, **kwargs)
            usage = _usage(response)
            generation.update(
                output=_response_output(response),
                usage_details=usage if usage["total"] else None,
                cost_details=llm_cost(usage["input"], usage["output"]) if usage["total"] else None,
            )
            return response

    try:
        completions.create = traced_create
    except Exception:
        return client
    return client
