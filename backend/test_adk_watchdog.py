"""
Phase 1 tests: ADK Watchdog narrator (Groq via LiteLLM).

- Offline tests use an injected probe, so they need no Prometheus, target service, or network.
- The live test calls Groq and runs only when GROQ_API_KEY is set.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import adk_agents  # noqa: E402


def _fake_probe(verdict="FAIL", findings=None):
    findings = findings if findings is not None else [{
        "finding_type": "HIGH_ERROR_RATE",
        "severity": "HIGH",
        "expected_value": "<= 5.00%",
        "actual_value": "40.00%",
        "description": "Runtime error rate of 40.00% (40/100) exceeds threshold of 5.00%.",
        "metadata": {},
    }]

    async def probe():
        return {
            "health_status": "healthy",
            "request_count": 100,
            "error_count": 40,
            "error_rate": 0.4,
            "latency_avg_seconds": 0.05,
            "latency_p95_seconds": 0.2,
            "findings": findings,
            "verdict": verdict,
        }
    return probe


def test_groq_model_name_uses_litellm_prefix(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    assert adk_agents.groq_model_name() == "groq/openai/gpt-oss-120b"
    monkeypatch.setenv("GROQ_MODEL", "llama-3.3-70b-versatile")
    assert adk_agents.groq_model_name() == "groq/llama-3.3-70b-versatile"


def test_agent_is_an_adk_llm_agent_backed_by_groq(monkeypatch):
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    from google.adk.agents import LlmAgent
    agent = adk_agents.build_watchdog_agent()
    assert isinstance(agent, LlmAgent)
    assert agent.name == "watchdog_narrator"
    assert agent.model.model == "groq/openai/gpt-oss-120b"
    assert agent.tools == []  # Phase 1: the probe is passed in, not called by the LLM


def test_deterministic_summary_lists_every_finding():
    text = adk_agents.deterministic_summary({
        "health_status": "healthy", "request_count": 100, "error_count": 40, "error_rate": 0.4,
        "latency_avg_seconds": None, "latency_p95_seconds": None, "verdict": "FAIL",
        "findings": [{"finding_type": "HIGH_ERROR_RATE", "severity": "HIGH", "description": "40% errors"}],
    })
    assert "Watchdog verdict: FAIL" in text
    assert "HIGH_ERROR_RATE (HIGH): 40% errors" in text
    assert "40.00%" in text


@pytest.mark.asyncio
async def test_fallback_without_groq_key_keeps_deterministic_verdict(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    result = await adk_agents.run_watchdog_agent(probe_fn=_fake_probe())
    assert result["llm_used"] is False
    assert result["fallback_reason"] == "GROQ_API_KEY is not set"
    assert result["probe"]["verdict"] == "FAIL"
    assert "HIGH_ERROR_RATE" in result["summary"]


@pytest.mark.asyncio
async def test_provider_error_falls_back_instead_of_failing(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")

    async def boom(agent, prompt):
        raise RuntimeError("429 rate limit reached")

    monkeypatch.setattr(adk_agents, "_run_llm", boom)
    result = await adk_agents.run_watchdog_agent(probe_fn=_fake_probe())
    assert result["llm_used"] is False
    assert "429" in result["fallback_reason"]
    assert result["probe"]["verdict"] == "FAIL"


@pytest.mark.asyncio
async def test_llm_summary_is_returned_when_model_answers(monkeypatch):
    monkeypatch.setenv("GROQ_API_KEY", "test-key-not-real")
    seen = {}

    async def fake_llm(agent, prompt):
        seen["prompt"] = prompt
        return "The service is failing: 40% of requests returned 5xx."

    monkeypatch.setattr(adk_agents, "_run_llm", fake_llm)
    result = await adk_agents.run_watchdog_agent(probe_fn=_fake_probe())
    assert result["llm_used"] is True
    assert result["summary"].startswith("The service is failing")
    assert '"verdict": "FAIL"' in seen["prompt"]


@pytest.mark.skipif(not os.getenv("GROQ_API_KEY"), reason="live Groq test needs GROQ_API_KEY")
@pytest.mark.asyncio
async def test_live_groq_narration():
    result = await adk_agents.run_watchdog_agent(probe_fn=_fake_probe())
    assert result["llm_used"] is True, result["fallback_reason"]
    assert result["summary"]
