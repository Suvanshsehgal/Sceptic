"""
Shared Groq client settings for the agents.

- No SDK retries: a rate-limited request fails at once and the agent uses its deterministic fallback, instead of
  the audit waiting through backoff.
- Daily quota cooldown: when the provider reports the daily token limit, LLM calls are skipped for a while, because
  every further call in the same run would fail the same way.
- Usage metering: every completion is counted (calls, failures, input and output tokens, per model), whether or not
  tracing is on. Only counts are kept, never prompts or responses. The performance and cost evaluation reads them.
"""
import os
import time
import logging
import threading
from typing import Any, Dict

logger = logging.getLogger("sceptic.llm")

REQUEST_TIMEOUT_SECONDS = float(os.getenv("SCEPTIC_LLM_TIMEOUT_SECONDS", "30"))
QUOTA_COOLDOWN_SECONDS = int(os.getenv("SCEPTIC_LLM_QUOTA_COOLDOWN_SECONDS", "3600"))

_quota_blocked_until = 0.0


class UsageMeter:
    """Thread-safe counters of LLM calls and tokens, per model."""

    def __init__(self):
        self._lock = threading.Lock()
        self._totals: Dict[str, Dict[str, int]] = {}

    def add(self, model: str, input_tokens: int, output_tokens: int, failed: bool = False) -> None:
        with self._lock:
            row = self._totals.setdefault(
                model or "unknown", {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0}
            )
            row["calls"] += 1
            row["failed"] += int(failed)
            row["input_tokens"] += int(input_tokens or 0)
            row["output_tokens"] += int(output_tokens or 0)

    def snapshot(self) -> Dict[str, Dict[str, int]]:
        with self._lock:
            return {model: dict(row) for model, row in self._totals.items()}

    def totals(self) -> Dict[str, int]:
        snap = self.snapshot()
        return {key: sum(row[key] for row in snap.values())
                for key in ("calls", "failed", "input_tokens", "output_tokens")}

    def reset(self) -> None:
        with self._lock:
            self._totals.clear()


METER = UsageMeter()


def _metered(client: Any) -> Any:
    """Wraps chat.completions.create so each call is counted. Errors are counted and re-raised unchanged."""
    try:
        completions = client.chat.completions
        original = completions.create
    except Exception:
        return client

    def create(*args, **kwargs):
        model = str(kwargs.get("model") or "unknown")
        try:
            response = original(*args, **kwargs)
        except Exception:
            METER.add(model, 0, 0, failed=True)
            raise
        usage = getattr(response, "usage", None)
        METER.add(model, getattr(usage, "prompt_tokens", 0), getattr(usage, "completion_tokens", 0))
        return response

    completions.create = create
    return client


def make_groq_client(api_key: str):
    from groq import Groq
    import tracing
    client = Groq(api_key=api_key, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)
    client = _metered(client)
    # Returns the client unchanged unless tracing is configured; then every completion is recorded as a generation.
    return tracing.wrap_groq_client(client)


def llm_blocked() -> bool:
    """True while the daily quota cooldown is active. Callers should use their fallback without calling the model."""
    return time.time() < _quota_blocked_until


def note_llm_error(error: Exception) -> None:
    """Start the cooldown when the error is a daily-quota limit. Per-minute limits do not start it."""
    global _quota_blocked_until
    text = str(error).lower()
    if ("429" in text or "rate limit" in text or "rate_limit" in text) and ("per day" in text or "tokens per day" in text or "tpd" in text):
        _quota_blocked_until = time.time() + QUOTA_COOLDOWN_SECONDS
        logger.warning(f"Groq daily token quota reached; LLM calls are skipped for {QUOTA_COOLDOWN_SECONDS}s.")
