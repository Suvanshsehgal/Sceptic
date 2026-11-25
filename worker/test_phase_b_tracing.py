"""
Phase B: Langfuse tracing (auditability and provenance).

A real Langfuse client is used with an in-memory span exporter, so these tests check the actual span tree and
attributes that would be exported, without a Langfuse server, a network, an LLM or Docker.
"""
import json
import os
import sys
import tempfile
import uuid
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.dirname(__file__))

import tracing
from audit_service import AuditService
from blind_tester import SpecificationMetadata
from orchestrator import AuditOrchestrator

SOURCE_SECRET = "ZEBRA_UNIQUE_SOURCE_TOKEN_91827"


@pytest.fixture
def traced(monkeypatch):
    """Installs a Langfuse client that exports to memory. Yields a function returning the finished spans."""
    from langfuse import Langfuse
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

    for name in ("SCEPTIC_TRACE_CONTENT", "SCEPTIC_LLM_PRICE_INPUT_PER_1M", "SCEPTIC_LLM_PRICE_OUTPUT_PER_1M"):
        monkeypatch.delenv(name, raising=False)
    exporter = InMemorySpanExporter()
    client = Langfuse(
        public_key=f"pk-lf-{uuid.uuid4().hex}", secret_key="sk-lf-test", host="http://127.0.0.1:9",
        span_exporter=exporter, tracer_provider=TracerProvider(), flush_interval=0.1, mask=tracing._langfuse_mask,
    )
    tracing.reset()
    tracing.configure(client)

    def spans():
        client.flush()
        return list(exporter.get_finished_spans())

    yield spans
    tracing.reset()
    client.shutdown()


@pytest.fixture(autouse=True)
def _clean_tracing_state():
    tracing.reset()
    yield
    tracing.reset()


def attr(span, key):
    value = span.attributes.get(f"langfuse.observation.{key}")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except ValueError:
            return value
    return value


def by_name(spans, name):
    found = [s for s in spans if s.name == name]
    assert found, f"no span named {name}; have {[s.name for s in spans]}"
    return found[0]


def everything(spans) -> str:
    """All attribute text of all spans, for asserting that something was or was not exported."""
    return json.dumps([dict(s.attributes) for s in spans], default=str)


def finding(agent, severity="INFO", status="VALID", title="t"):
    return {"agent_name": agent, "severity": severity, "status": status, "title": title}


def stub_service(monkeypatch, file_checks=None, spec_findings=None, leak=None):
    service = AuditService()
    monkeypatch.setattr("audit_service.run_leak_hunter", lambda path: leak or [])
    monkeypatch.setattr("audit_service.run_purana_saman", lambda path: [])
    monkeypatch.setattr("audit_service.run_jhooti_docstring", lambda source, path: [])
    monkeypatch.setattr(service.orchestrator, "run_file_checks", lambda source, path, lang, *a, **k: (
        file_checks or {"fact_checker": [finding("Fact-Checker")], "security_guard": []}))
    monkeypatch.setattr(service.orchestrator, "run_spec_checks", lambda source, spec, path, *a, **k: list(spec_findings or []))
    return service


def write_module(tmp, text="def double(x):\n    '''Doubles.'''\n    return x * 2\n"):
    path = os.path.join(tmp, "m.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)
    return path


# ---------------------------------------------------------------- off by default

def test_tracing_is_off_without_keys(monkeypatch):
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert tracing.configured() is False
    assert tracing.enabled() is False
    with tracing.observation("x") as span:
        span.update(output={"a": 1})
        assert span.trace_id is None
    assert tracing.current_trace_context() is None
    assert tracing.trace_url("a" * 32) is None


def test_tracing_can_be_switched_off_even_with_keys(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("SCEPTIC_TRACING", "off")
    assert tracing.configured() is False


def test_groq_client_is_returned_untouched_when_tracing_is_off():
    client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=lambda **k: None)))
    original = client.chat.completions.create
    assert tracing.wrap_groq_client(client) is client
    assert client.chat.completions.create is original


def test_a_client_that_cannot_start_disables_tracing_without_raising(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")

    def boom():
        raise RuntimeError("cannot start")

    monkeypatch.setattr(tracing, "_create_client", boom)
    assert tracing.enabled() is False
    with tracing.observation("x"):
        pass


# ---------------------------------------------------------------- fail-safe

def test_tracing_errors_never_reach_the_caller():
    class Broken:
        def start_as_current_observation(self, **kwargs):
            raise RuntimeError("langfuse is down")

    tracing.configure(Broken())
    ran = []
    with tracing.observation("x") as span:
        span.update(output="ignored")
        ran.append(True)
    assert ran == [True]


def test_exception_in_the_body_marks_the_span_and_is_reraised(traced):
    with pytest.raises(ValueError, match="bad input"):
        with tracing.observation("work", as_type="agent"):
            raise ValueError("bad input")
    span = by_name(traced(), "work")
    assert attr(span, "level") == "ERROR"
    assert "bad input" in attr(span, "status_message")


# ---------------------------------------------------------------- audit trace

def test_audit_is_one_trace_with_agent_spans_nested_under_the_root(traced, monkeypatch):
    service = stub_service(
        monkeypatch,
        spec_findings=[finding("Blind-Tester", "HIGH", "FAIL", "spec")],
        leak=[finding("Leak-Hunter", "LOW", title="s")],
    )
    with tempfile.TemporaryDirectory() as tmp:
        report = service.audit_report(write_module(tmp))
    spans = traced()

    root = by_name(spans, "sceptic.audit")
    assert root.parent is None
    assert {s.context.trace_id for s in spans} == {root.context.trace_id}
    assert report.trace_id == format(root.context.trace_id, "032x")

    # Leak-Hunter runs on a pool thread: it must still be under the audit, not an orphan trace.
    leak = by_name(spans, "agent.Leak-Hunter")
    assert leak.parent.span_id == root.context.span_id
    assert attr(leak, "type") == "agent"
    assert attr(leak, "output")["findings"] == 1

    synth = by_name(spans, "agent.Synthesizer")
    assert attr(synth, "output")["recommendation"] == report.recommendation
    assert attr(root, "output")["trust_score"] == report.trust_score


def test_pipeline_trace_carries_trace_id_and_all_three_agents(traced, monkeypatch):
    class Stub(AuditOrchestrator):
        def run_file_checks(self, *a, **k):
            return {"fact_checker": [finding("Fact-Checker")], "security_guard": [finding("Security-Guard", "LOW")]}

        def run_spec_checks(self, *a, **k):
            return [finding("Blind-Tester")]

    spec = SpecificationMetadata(function_name="f", docstring="d", specification="s")
    report = Stub().run_pipeline("def f(): pass", spec, file_path="t.py")
    spans = traced()
    root = by_name(spans, "sceptic.pipeline")
    assert report["trace_id"] == format(root.context.trace_id, "032x")
    assert by_name(spans, "agent.Synthesizer").parent.span_id == root.context.span_id


def test_agent_spans_record_counts_and_warn_on_agent_errors(traced, monkeypatch):
    # use the real orchestrator methods with the agent functions stubbed
    monkeypatch.setattr("orchestrator.run_fact_checker", lambda **k: [finding("Fact-Checker", "MEDIUM", "ERROR", "tool broke")])
    monkeypatch.setattr("orchestrator.run_security_guard", lambda **k: [finding("Security-Guard", "HIGH", "INVALID", "x")])
    AuditOrchestrator().run_file_checks("print(1)", "a.py", "python")
    spans = traced()
    fact = by_name(spans, "agent.Fact-Checker")
    assert attr(fact, "level") == "WARNING" and attr(fact, "status_message") == "tool broke"
    assert attr(fact, "output") == {"findings": 1, "severities": {"MEDIUM": 1}, "errors": 1}
    sec = by_name(spans, "agent.Security-Guard")
    assert attr(sec, "level") in (None, "DEFAULT")
    assert attr(sec, "output")["severities"] == {"HIGH": 1}


def test_an_incomplete_audit_is_flagged_on_the_root_span(traced, monkeypatch):
    service = stub_service(monkeypatch)

    def boom(*a, **k):
        raise RuntimeError("scanner exploded")

    monkeypatch.setattr(service.orchestrator, "run_file_checks", boom)
    with tempfile.TemporaryDirectory() as tmp:
        report = service.audit_report(write_module(tmp))
    root = by_name(traced(), "sceptic.audit")
    assert attr(root, "level") == "WARNING"
    assert "audit incomplete" in attr(root, "status_message")
    assert report.recommendation != "APPROVE"


# ---------------------------------------------------------------- what is (not) exported

def test_source_code_is_not_exported_by_default(traced, monkeypatch):
    source = f"def double(x):\n    '''Doubles.'''\n    return x * 2  # {SOURCE_SECRET}\n"
    service = stub_service(monkeypatch)
    # The real orchestrator spans are exercised by stubbing the agent functions, not the orchestrator methods.
    monkeypatch.undo()
    monkeypatch.setattr("audit_service.run_leak_hunter", lambda path: [])
    monkeypatch.setattr("audit_service.run_purana_saman", lambda path: [])
    monkeypatch.setattr("audit_service.run_jhooti_docstring", lambda source, path: [])
    monkeypatch.setattr("orchestrator.run_fact_checker", lambda **k: [])
    monkeypatch.setattr("orchestrator.run_security_guard", lambda **k: [])
    monkeypatch.setattr("orchestrator.run_blind_tester", lambda **k: [])
    with tempfile.TemporaryDirectory() as tmp:
        service.audit_report(write_module(tmp, source))
    spans = traced()
    assert SOURCE_SECRET not in everything(spans)
    fact = attr(by_name(spans, "agent.Fact-Checker"), "input")
    assert fact["source_chars"] == len(source) and len(fact["source_sha256"]) == 12


def test_content_mode_sends_clipped_masked_source_but_never_to_the_blind_tester(traced, monkeypatch):
    monkeypatch.setenv("SCEPTIC_TRACE_CONTENT", "true")
    source = (
        f'def double(x):\n    """Doubles."""\n    key = "gsk_abcdefghijklmnopqrstuvwxyz0123"\n'
        f'    password = "hunter2hunter2"\n    return x * 2  # {SOURCE_SECRET}\n'
    )
    monkeypatch.setattr("orchestrator.run_fact_checker", lambda **k: [])
    monkeypatch.setattr("orchestrator.run_security_guard", lambda **k: [])
    monkeypatch.setattr("orchestrator.run_blind_tester", lambda **k: [])
    spec = SpecificationMetadata(function_name="double", docstring="Doubles.", specification="Doubles x.")
    AuditOrchestrator().run_pipeline(source, spec, file_path="m.py")
    spans = traced()

    fact = by_name(spans, "agent.Fact-Checker")
    assert SOURCE_SECRET in json.dumps(attr(fact, "input"))                 # content mode: source is there
    assert "gsk_abcdefghijklmnop" not in everything(spans)                  # but credentials are masked
    assert "hunter2hunter2" not in everything(spans)
    assert "[REDACTED]" in json.dumps(attr(fact, "input"))

    blind = by_name(spans, "agent.Blind-Tester")
    assert SOURCE_SECRET not in json.dumps(attr(blind, "input"))            # implementation never on the blind span
    assert "x * 2" not in json.dumps(attr(blind, "input"))


# ---------------------------------------------------------------- LLM generations

def fake_groq(response=None, error=None):
    def create(**kwargs):
        if error:
            raise error
        return response

    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def groq_response(text="a verdict", prompt=120, completion=30):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, total_tokens=prompt + completion),
    )


def test_groq_call_becomes_a_generation_with_usage_and_no_prompt_text(traced):
    client = tracing.wrap_groq_client(fake_groq(groq_response()))
    messages = [{"role": "system", "content": "be strict"}, {"role": "user", "content": f"review {SOURCE_SECRET}"}]
    with tracing.observation("agent.X", as_type="agent"):
        result = client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, temperature=0.1)
    assert result.choices[0].message.content == "a verdict"      # the response is returned untouched
    spans = traced()
    gen = by_name(spans, "groq.chat.completions")
    assert attr(gen, "type") == "generation"
    assert attr(gen, "model.name") == "openai/gpt-oss-120b"
    assert attr(gen, "usage_details") == {"input": 120, "output": 30, "total": 150}
    assert attr(gen, "cost_details") is None
    assert attr(gen, "input")["roles"] == ["system", "user"]
    assert gen.parent.span_id == by_name(spans, "agent.X").context.span_id
    assert SOURCE_SECRET not in everything(spans) and "a verdict" not in everything(spans)


def test_cost_is_attached_when_prices_are_configured(traced, monkeypatch):
    monkeypatch.setenv("SCEPTIC_LLM_PRICE_INPUT_PER_1M", "0.15")
    monkeypatch.setenv("SCEPTIC_LLM_PRICE_OUTPUT_PER_1M", "0.60")
    client = tracing.wrap_groq_client(fake_groq(groq_response(prompt=1_000_000, completion=1_000_000)))
    client.chat.completions.create(model="m", messages=[])
    cost = attr(by_name(traced(), "groq.chat.completions"), "cost_details")
    assert cost["input"] == pytest.approx(0.15) and cost["output"] == pytest.approx(0.60)
    assert cost["total"] == pytest.approx(0.75)


def test_failed_groq_call_is_recorded_and_the_error_still_propagates(traced):
    client = tracing.wrap_groq_client(fake_groq(error=RuntimeError("429 rate limit")))
    with pytest.raises(RuntimeError, match="429"):
        client.chat.completions.create(model="m", messages=[{"role": "user", "content": "x"}])
    gen = by_name(traced(), "groq.chat.completions")
    assert attr(gen, "level") == "ERROR" and "429" in attr(gen, "status_message")


# ---------------------------------------------------------------- MCP boundary

def test_trace_context_round_trip_and_rejection_of_garbage():
    ctx = {"trace_id": "a" * 32, "parent_span_id": "b" * 16}
    assert tracing.decode_context(tracing.encode_context(ctx)) == ctx
    for bad in ("", "not json", "{}", '{"trace_id": "zz", "parent_span_id": "yy"}',
                json.dumps({"trace_id": "A" * 32, "parent_span_id": "b" * 16}),
                json.dumps({"trace_id": "a" * 31, "parent_span_id": "b" * 16})):
        assert tracing.decode_context(bad) is None
    assert tracing.encode_context(None) == ""


def test_mcp_tool_joins_the_callers_trace_through_the_trace_context_argument(traced):
    import mcp_server

    tool = mcp_server.mcp._tool_manager._tools["verify_api_usage"]
    assert "trace_context" in tool.parameters["properties"]
    assert "trace_context" not in (tool.parameters.get("required") or [])

    with tracing.observation("mcp.verify_api_usage", as_type="tool") as client_span:
        context = tracing.encode_context(tracing.current_trace_context())
        # What the server process does when the call arrives:
        output = tool.fn(source_code=f"import os  # {SOURCE_SECRET}\n", file_path="a.py", trace_context=context)
    assert isinstance(json.loads(output), list)
    spans = traced()
    server_side = by_name(spans, "tool.verify_api_usage")
    assert server_side.context.trace_id == by_name(spans, "mcp.verify_api_usage").context.trace_id
    assert format(server_side.parent.span_id, "016x") == client_span.id
    assert SOURCE_SECRET not in everything(spans)


def test_mcp_tool_ignores_a_forged_trace_context(traced):
    import mcp_server

    tool = mcp_server.mcp._tool_manager._tools["verify_api_usage"]
    out = tool.fn(source_code="x = 1\n", trace_context='{"trace_id": "../../etc", "parent_span_id": 1}')
    assert isinstance(json.loads(out), list)
    span = by_name(traced(), "tool.verify_api_usage")
    assert span.parent is None            # started its own trace instead of trusting the value


def test_mcp_tool_works_normally_with_tracing_off():
    import mcp_server

    tool = mcp_server.mcp._tool_manager._tools["verify_api_usage"]
    assert isinstance(json.loads(tool.fn(source_code="import os\nos.path.nope(1)\n")), list)


def test_mcp_client_sends_context_only_when_a_trace_is_active(traced, monkeypatch):
    from mcp_client import SceptiMCPClient

    sent = []
    client = SceptiMCPClient()
    monkeypatch.setattr(client, "_call_tool", lambda name, arguments, timeout: sent.append(dict(arguments)) or "[]")

    client.call_tool("verify_api_usage", {"source_code": "x = 1", "file_path": "a.py"})
    assert json.loads(sent[0]["trace_context"])["trace_id"]                # opened its own span, so it has a context

    spans = traced()
    mcp_span = by_name(spans, "mcp.verify_api_usage")
    assert attr(mcp_span, "type") == "tool"
    inputs = attr(mcp_span, "input")
    assert inputs["file_path"] == "a.py"
    assert "source_code" not in inputs and inputs["source_code_chars"] == 5   # even short source is not sent
    assert attr(mcp_span, "output") == {"findings": 0, "severities": {}, "errors": 0}


def test_mcp_client_sends_no_context_when_tracing_is_off(monkeypatch):
    from mcp_client import SceptiMCPClient

    sent = []
    client = SceptiMCPClient()
    monkeypatch.setattr(client, "_call_tool", lambda name, arguments, timeout: sent.append(dict(arguments)) or "[]")
    client.call_tool("verify_api_usage", {"source_code": "x = 1"})
    assert "trace_context" not in sent[0]


# ---------------------------------------------------------------- helpers

def test_trace_url_is_built_from_the_public_url_without_a_network_call(monkeypatch):
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_HOST", "http://langfuse:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_URL", "https://traces.example.com/")
    assert tracing.trace_url("c" * 32) == f"https://traces.example.com/trace/{'c' * 32}"
    assert tracing.trace_url(None) is None


def test_wrap_context_carries_the_trace_into_other_threads(traced):
    from concurrent.futures import ThreadPoolExecutor

    def child():
        with tracing.observation("in-thread"):
            pass

    with tracing.observation("parent"):
        bound = tracing.wrap_context(child)          # captured here, in the submitting thread
        with ThreadPoolExecutor(max_workers=4) as pool:
            list(pool.map(lambda _: bound(), range(8)))
    spans = traced()
    parent = by_name(spans, "parent")
    children = [s for s in spans if s.name == "in-thread"]
    assert len(children) == 8
    assert all(c.parent.span_id == parent.context.span_id for c in children)


def test_mask_text_covers_common_credential_shapes():
    text = 'k=gsk_abcdefghijklmnopqrstuvwx a=AKIAABCDEFGHIJKLMNOP password = "s3cretvalue" ok=1'
    masked = tracing.mask_text(text)
    assert "gsk_abc" not in masked and "AKIAABC" not in masked and "s3cretvalue" not in masked
    assert masked.endswith("ok=1") and 'password = "[REDACTED]"' in masked


def test_tool_input_summary_is_an_allowlist():
    summary = tracing.summarize_tool_input({
        "source_code": "x = 1",                                  # short, still not sent
        "docstring": "Adds numbers",
        "implementation_code": "def f(): return 1",
        "body": "## summary text",
        "file_path": r"C:\Users\Someone\proj\src\pkg\mod.py",
        "language": "python",
        "run_llm_analysis": True,
        "pr_number": 7,
        "trace_context": '{"trace_id": "x"}',
        "weird": {"nested": 1},
    })
    assert summary["language"] == "python" and summary["run_llm_analysis"] is True and summary["pr_number"] == 7
    assert summary["file_path"] == "src/pkg/mod.py"
    assert "Someone" not in json.dumps(summary)
    for hidden in ("x = 1", "Adds numbers", "def f()", "summary text"):
        assert hidden not in json.dumps(summary)
    for key in ("source_code", "docstring", "implementation_code", "body"):
        assert key not in summary and f"{key}_chars" in summary and len(summary[f"{key}_sha256"]) == 12
    assert "trace_context" not in summary and summary["weird"] == "dict"


def test_short_path_keeps_the_tail_for_windows_and_posix_paths():
    assert tracing.short_path(r"C:\Users\Someone\proj\src\mod.py") == "proj/src/mod.py"
    assert tracing.short_path("/home/someone/proj/src/mod.py") == "proj/src/mod.py"
    assert tracing.short_path("mod.py") == "mod.py" and tracing.short_path("") == ""


def test_api_response_exposes_trace_url_only_when_tracing_is_configured(monkeypatch):
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
    import schemas
    from datetime import datetime, timezone
    from uuid import uuid4

    def make(trace_id):
        return schemas.AuditRunResponse(
            id=uuid4(), pull_request_id=uuid4(), commit_sha="c", status="COMPLETED", idempotency_key="k",
            created_at=datetime.now(timezone.utc), trace_id=trace_id,
        )

    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    assert make("a" * 32).trace_url is None
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk")
    monkeypatch.setenv("LANGFUSE_PUBLIC_URL", "https://lf.example.com")
    assert make("a" * 32).trace_url == f"https://lf.example.com/trace/{'a' * 32}"
    assert make(None).trace_url is None


def test_cli_submission_drops_a_malformed_trace_id():
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend"))
    import schemas
    ok = schemas.CLIAuditSubmission(target_path="x", trust_score=90, trace_id="b" * 32)
    bad = schemas.CLIAuditSubmission(target_path="x", trust_score=90, trace_id="../../evil")
    assert ok.trace_id == "b" * 32
    assert bad.trace_id is None


def test_framework_instrumentation_is_off_in_default_privacy_mode(traced, monkeypatch):
    monkeypatch.delenv("SCEPTIC_TRACE_CONTENT", raising=False)
    assert tracing.instrument_frameworks(("crewai", "google_adk")) == []
