"""
Shared Groq client settings for the agents.

- No SDK retries: a rate-limited request fails at once and the agent uses its deterministic fallback, instead of
  the audit waiting through backoff.
- Daily quota cooldown: when the provider reports the daily token limit, LLM calls are skipped for a while, because
  every further call in the same run would fail the same way.
"""
import os
import time
import logging

logger = logging.getLogger("sceptic.llm")

REQUEST_TIMEOUT_SECONDS = float(os.getenv("SCEPTIC_LLM_TIMEOUT_SECONDS", "30"))
QUOTA_COOLDOWN_SECONDS = int(os.getenv("SCEPTIC_LLM_QUOTA_COOLDOWN_SECONDS", "3600"))

_quota_blocked_until = 0.0


def make_groq_client(api_key: str):
    from groq import Groq
    return Groq(api_key=api_key, max_retries=0, timeout=REQUEST_TIMEOUT_SECONDS)


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
