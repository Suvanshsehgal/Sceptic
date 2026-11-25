"""
Phase E: usage metering, timing and cost arithmetic used by evaluation/run_perf.py.

These tests check the bookkeeping, not the performance itself. The measured numbers are produced by running
run_perf.py and are stored in evaluation/results/.
"""
import importlib.util
import json
import os
import sys
import threading

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import llm_client
from llm_client import UsageMeter, _metered

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_perf_module():
    spec = importlib.util.spec_from_file_location("run_perf", os.path.join(ROOT, "evaluation", "run_perf.py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------- usage meter

def test_meter_totals_per_model_and_overall():
    meter = UsageMeter()
    meter.add("a", 100, 20)
    meter.add("a", 50, 5)
    meter.add("b", 10, 1, failed=True)
    assert meter.snapshot()["a"] == {"calls": 2, "failed": 0, "input_tokens": 150, "output_tokens": 25}
    assert meter.totals() == {"calls": 3, "failed": 1, "input_tokens": 160, "output_tokens": 26}
    meter.reset()
    assert meter.totals() == {"calls": 0, "failed": 0, "input_tokens": 0, "output_tokens": 0}


def test_meter_is_safe_under_threads():
    meter = UsageMeter()

    def work():
        for _ in range(200):
            meter.add("m", 1, 1)

    threads = [threading.Thread(target=work) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert meter.totals()["calls"] == 1600 and meter.totals()["input_tokens"] == 1600


class _Usage:
    def __init__(self, prompt, completion):
        self.prompt_tokens = prompt
        self.completion_tokens = completion


class _Response:
    def __init__(self, prompt, completion):
        self.usage = _Usage(prompt, completion)


def test_metered_client_counts_successful_calls_and_passes_responses_through(monkeypatch):
    monkeypatch.setattr(llm_client, "METER", UsageMeter())
    response = _Response(120, 30)

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return response

    client = _metered(Client())
    assert client.chat.completions.create(model="openai/gpt-oss-120b", messages=[]) is response
    assert llm_client.METER.totals() == {"calls": 1, "failed": 0, "input_tokens": 120, "output_tokens": 30}


def test_metered_client_counts_failures_and_reraises(monkeypatch):
    monkeypatch.setattr(llm_client, "METER", UsageMeter())

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    raise RuntimeError("429 rate limit")

    client = _metered(Client())
    with pytest.raises(RuntimeError, match="429"):
        client.chat.completions.create(model="m", messages=[])
    assert llm_client.METER.totals()["failed"] == 1


def test_metered_client_tolerates_a_response_without_usage(monkeypatch):
    monkeypatch.setattr(llm_client, "METER", UsageMeter())

    class Client:
        class chat:
            class completions:
                @staticmethod
                def create(**kwargs):
                    return object()

    _metered(Client()).chat.completions.create(model="m", messages=[])
    assert llm_client.METER.totals()["input_tokens"] == 0


# ---------------------------------------------------------------- performance harness arithmetic

def test_percentiles_use_nearest_rank_on_sorted_values():
    perf = load_perf_module()
    values = [1.0, 2.0, 3.0, 4.0, 5.0]
    assert perf.percentile(values, 50) == 3.0
    assert perf.percentile(values, 95) == 5.0
    assert perf.percentile([], 50) is None


def test_agent_timer_counts_error_findings_as_errors_and_exceptions_too():
    perf = load_perf_module()
    timer = perf.AgentTimer()

    def ok(path):
        return [{"status": "PASS"}]

    def unavailable(*a, **k):
        return [{"status": "ERROR", "title": "sandbox unavailable"}]

    def crash(*a, **k):
        raise RuntimeError("boom")

    wrapped_ok, wrapped_unavailable, wrapped_crash = timer.wrap("A", ok), timer.wrap("B", unavailable), timer.wrap("C", crash)
    wrapped_ok("p")
    wrapped_unavailable("p")
    with pytest.raises(RuntimeError):
        wrapped_crash("p")
    assert timer.errors == {"B": 1, "C": 1}
    assert len(timer.snapshot()["A"]) == 1


def test_markdown_states_when_cost_was_not_computed():
    perf = load_perf_module()
    result = {
        "mode": "deterministic", "cases": 1, "repeats": 1, "audits": 1,
        "wall_seconds": {"total": 1, "p50": 1, "p95": 1, "mean": 1, "max": 1},
        "agents": {}, "agents_unavailable_in_this_run": [],
        "llm": {"calls_per_audit": 0, "failed_total": 0, "input_tokens_per_audit": 0, "output_tokens_per_audit": 0},
        "cost": {"price_input_per_million_usd": None, "price_output_per_million_usd": None,
                 "cost_per_audit_usd": None, "cost_per_1000_audits_usd": None},
    }
    assert "not computed" in perf.markdown(result)


# ---------------------------------------------------------------- dataset matches the evaluation README

def test_manifest_has_twelve_bugs_and_fifteen_clean_controls():
    with open(os.path.join(ROOT, "evaluation", "seeded_bugs", "manifest.json"), encoding="utf-8") as f:
        cases = json.load(f)["cases"]
    assert sum(1 for c in cases if c["kind"] == "bug") == 12
    assert sum(1 for c in cases if c["kind"] == "clean") == 15
    for case in cases:
        assert os.path.exists(os.path.join(ROOT, "evaluation", "seeded_bugs", case["file"])), case["file"]
