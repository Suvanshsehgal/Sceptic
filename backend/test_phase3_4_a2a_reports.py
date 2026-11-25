"""
Phase 3 and Phase 4 tests: A2A messaging (Watchdog -> Rollback), Markdown report routes, and the Q&A tool binding.

Route tests use the real FastAPI app with the database, Watchdog, and Rollback replaced by fakes, so they run
offline. The A2A protocol test sends a message through an in-process app.
"""
import os
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import a2a_subset as a2a  # noqa: E402  (in-house A2A subset; see a2a_subset.py)
import adk_agents  # noqa: E402
import main  # noqa: E402
import reports  # noqa: E402
import schemas  # noqa: E402

USER_ID = uuid.uuid4()
OWN_DEPLOYMENT = uuid.uuid4()
OTHER_DEPLOYMENT = uuid.uuid4()


def _deployment(deployment_id):
    return SimpleNamespace(id=deployment_id, environment="production", commit_sha="abc123def456789", status="ACTIVE")


@pytest.fixture
def client(monkeypatch):
    user = SimpleNamespace(id=USER_ID)
    main.app.dependency_overrides[main.get_current_user] = lambda: user
    main.app.dependency_overrides[main.get_db] = lambda: None

    async def fake_authorized(deployment_id, user_id, db):
        if deployment_id == OWN_DEPLOYMENT:
            return _deployment(deployment_id)
        raise HTTPException(status_code=404, detail="Deployment not found")

    monkeypatch.setattr(main, "_get_authorized_deployment", fake_authorized)
    transport = httpx.ASGITransport(app=main.app)
    yield httpx.AsyncClient(transport=transport, base_url="http://test")
    main.app.dependency_overrides.clear()


# ---------- Phase 3: protocol ----------

def test_agent_cards_are_public_and_name_their_endpoints():
    watchdog = a2a.agent_card("watchdog", base_url="http://sceptic.test")
    rollback = a2a.agent_card("rollback", base_url="http://sceptic.test")
    assert watchdog["url"] == "http://sceptic.test/a2a/watchdog"
    assert rollback["url"] == "http://sceptic.test/a2a/rollback"
    assert rollback["authentication"]["schemes"] == ["Bearer"]


def test_read_request_rejects_wrong_method_and_missing_data():
    with pytest.raises(a2a.A2AError):
        a2a.read_request({"jsonrpc": "2.0", "id": 1, "method": "tasks/get", "params": {}})
    with pytest.raises(a2a.A2AError):
        a2a.read_request({"jsonrpc": "2.0", "id": 1, "method": "message/send",
                          "params": {"message": {"parts": [{"kind": "text", "text": "hi"}]}}})


def test_request_and_response_round_trip():
    req = a2a.make_request({"deployment_id": "x"}, request_id="7")
    assert a2a.read_request(req) == {"deployment_id": "x"}
    reply = a2a.make_response("7", {"ok": True})
    assert a2a.response_data(reply) == {"ok": True}


def test_peer_error_becomes_a2a_error():
    with pytest.raises(a2a.A2AError, match="-32602"):
        a2a.response_data({"jsonrpc": "2.0", "id": 1, "error": {"code": -32602, "message": "bad"}})


@pytest.mark.asyncio
async def test_send_message_round_trip_through_an_in_process_agent(monkeypatch):
    """A tiny peer built with the same helpers answers a message sent by send_message."""
    peer = FastAPI()
    seen = {}

    @peer.post("/peer")
    async def peer_endpoint(request: Request):
        seen["auth"] = request.headers.get("authorization")
        payload = a2a.read_request(await request.json())
        return a2a.make_response("r1", {"echo": payload["deployment_id"]})

    real_client = httpx.AsyncClient

    def client_factory(**kwargs):
        kwargs["transport"] = httpx.ASGITransport(app=peer)
        return real_client(**kwargs)

    monkeypatch.setattr(a2a.httpx, "AsyncClient", client_factory)
    reply = await a2a.send_message("http://peer/peer", {"deployment_id": "d-1"}, "Bearer tok")
    assert reply == {"echo": "d-1"}
    assert seen["auth"] == "Bearer tok"


# ---------- Phase 3: routes ----------

@pytest.mark.asyncio
async def test_agent_card_routes(client):
    async with client:
        resp = await client.get("/a2a/rollback/.well-known/agent.json")
        assert resp.status_code == 200
        assert resp.json()["name"] == "Sceptic Rollback Agent"


@pytest.mark.asyncio
async def test_watchdog_fail_sends_a2a_to_rollback_with_the_callers_token(client, monkeypatch):
    # Automatic rollback is opt-in (Phase D). This test covers the opted-in path.
    monkeypatch.setenv("SCEPTIC_A2A_AUTO_ROLLBACK", "true")
    calls = {}

    class FakeWatchdog:
        async def evaluate(self, deployment, db):
            return SimpleNamespace(status=schemas.VerificationStatus.FAIL, summary="error spike",
                                   model_dump=lambda mode=None: {"status": "FAIL", "findings": []})

    async def fake_send(url, payload, authorization):
        calls.update(url=url, payload=payload, authorization=authorization)
        return {"rollback": {"status": "SUCCESS", "success": True}}

    monkeypatch.setattr(main, "PipelineWatchdog", FakeWatchdog)
    monkeypatch.setattr(a2a, "send_message", fake_send)

    async with client:
        resp = await client.post(
            "/a2a/watchdog",
            json=a2a.make_request({"deployment_id": str(OWN_DEPLOYMENT)}),
            headers={"Authorization": "Bearer tok-123"},
        )
    body = resp.json()
    data = a2a.response_data(body)
    assert data["rollback"] == {"rollback": {"status": "SUCCESS", "success": True}}
    assert calls["url"].endswith("/a2a/rollback")
    assert calls["payload"]["trigger_source"] == "WATCHDOG"
    assert calls["payload"]["reason"].startswith("Watchdog FAIL")
    assert calls["authorization"] == "Bearer tok-123"


@pytest.mark.asyncio
async def test_watchdog_pass_does_not_call_rollback(client, monkeypatch):
    class PassingWatchdog:
        async def evaluate(self, deployment, db):
            return SimpleNamespace(status=schemas.VerificationStatus.PASS, summary="ok",
                                   model_dump=lambda mode=None: {"status": "PASS", "findings": []})

    async def must_not_send(*args, **kwargs):
        raise AssertionError("rollback must not be called on PASS")

    monkeypatch.setattr(main, "PipelineWatchdog", PassingWatchdog)
    monkeypatch.setattr(a2a, "send_message", must_not_send)

    async with client:
        resp = await client.post("/a2a/watchdog", json=a2a.make_request({"deployment_id": str(OWN_DEPLOYMENT)}))
    assert a2a.response_data(resp.json())["rollback"] is None


@pytest.mark.asyncio
async def test_rollback_route_passes_the_trigger_to_the_safety_agent(client, monkeypatch):
    seen = {}

    class FakeRollback:
        async def evaluate_and_execute(self, deployment, reason, trigger_source, db, **kwargs):
            seen.update(reason=reason, trigger_source=trigger_source, deployment=deployment.id)
            return SimpleNamespace(model_dump=lambda mode=None: {"status": "ABORTED", "success": False})

    monkeypatch.setattr(main, "RollbackAgent", FakeRollback)
    async with client:
        resp = await client.post("/a2a/rollback", json=a2a.make_request(
            {"deployment_id": str(OWN_DEPLOYMENT), "reason": "Watchdog FAIL: spike", "trigger_source": "WATCHDOG"}))
    assert a2a.response_data(resp.json())["rollback"]["status"] == "ABORTED"
    assert seen["trigger_source"] == "WATCHDOG"
    assert seen["deployment"] == OWN_DEPLOYMENT


@pytest.mark.asyncio
async def test_rollback_route_rejects_bad_payload_without_running(client, monkeypatch):
    class MustNotRun:
        async def evaluate_and_execute(self, **kwargs):
            raise AssertionError("rollback must not run on a bad request")

    monkeypatch.setattr(main, "RollbackAgent", MustNotRun)
    async with client:
        resp = await client.post("/a2a/rollback", json=a2a.make_request({"reason": "no deployment id"}))
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == -32602


@pytest.mark.asyncio
async def test_rollback_route_denies_other_users_deployment(client, monkeypatch):
    class MustNotRun:
        async def evaluate_and_execute(self, **kwargs):
            raise AssertionError("rollback must not run for another user's deployment")

    monkeypatch.setattr(main, "RollbackAgent", MustNotRun)
    async with client:
        resp = await client.post("/a2a/rollback", json=a2a.make_request(
            {"deployment_id": str(OTHER_DEPLOYMENT), "reason": "try it", "trigger_source": "WATCHDOG"}))
    assert resp.status_code == 404


# ---------- Phase 4: reports and Q&A ----------

@pytest.mark.asyncio
async def test_report_route_writes_markdown_and_returns_it(client, monkeypatch, tmp_path):
    async def fake_run():
        return {"probe": {"verdict": "FAIL", "health_status": "healthy", "request_count": 50, "error_count": 25,
                          "error_rate": 0.5, "latency_avg_seconds": None, "latency_p95_seconds": 0.1,
                          "findings": [{"finding_type": "HIGH_ERROR_RATE", "severity": "HIGH",
                                        "description": "50% errors"}]},
                "summary": "Errors are high.", "llm_used": False, "fallback_reason": "GROQ_API_KEY is not set"}

    written = {}

    def fake_write(name, markdown, directory=None):
        written["name"] = name
        path = tmp_path / name
        path.write_text(markdown, encoding="utf-8")
        return path

    monkeypatch.setattr(adk_agents, "run_watchdog_agent", fake_run)
    monkeypatch.setattr(main.reports, "write_incident_report", fake_write)

    async with client:
        resp = await client.post(f"/deployments/{OWN_DEPLOYMENT}/report")
    body = resp.json()
    assert resp.status_code == 200
    assert body["report_name"].startswith(f"deployment-{OWN_DEPLOYMENT}-")
    assert "**FAIL**" in body["markdown"]
    assert (tmp_path / written["name"]).exists()


@pytest.mark.asyncio
async def test_ask_route_blocks_another_users_deployment_report(client, monkeypatch):
    async def must_not_run(source, question, agent=None):
        raise AssertionError("LLM must not read another user's report")

    monkeypatch.setattr(adk_agents, "answer_from_source", must_not_run)
    other_report = f"deployment-{OTHER_DEPLOYMENT}-20260101T000000.md"
    async with client:
        resp = await client.post("/reports/ask", json={"source": other_report, "question": "what failed?"})
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_ask_route_answers_runbook_questions(client, monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    async with client:
        resp = await client.post("/reports/ask", json={
            "source": "high_error_rate.md", "question": "What is the first check?"})
    assert resp.status_code == 200
    assert resp.json()["llm_used"] is False
    assert "Runbook: high error rate" in resp.json()["content"]


def test_single_source_tool_cannot_read_other_files():
    tool = adk_agents._single_source_tool("high_error_rate.md")
    assert "error" in tool("deployment-x.md") or "error" in tool("other.md")
    assert "Runbook" in tool("high_error_rate.md")["content"]


def test_qa_agent_bound_to_one_source_uses_that_tool():
    agent = adk_agents.build_report_qa_agent(source_name="high_error_rate.md")
    assert len(agent.tools) == 1
    assert agent.tools[0] is not reports.read_markdown_source


# ---------- Phase 4: demo script helpers ----------

def test_demo_script_helpers_import():
    scripts_dir = Path(__file__).resolve().parent.parent / "scripts"
    sys.path.insert(0, str(scripts_dir))
    try:
        import demo_post_deploy
        assert callable(demo_post_deploy.main)
        assert callable(demo_post_deploy.send_traffic)
    finally:
        sys.path.remove(str(scripts_dir))


@pytest.mark.asyncio
async def test_watchdog_fail_does_not_roll_back_without_the_opt_in(client, monkeypatch):
    monkeypatch.delenv("SCEPTIC_A2A_AUTO_ROLLBACK", raising=False)

    class FakeWatchdog:
        async def evaluate(self, deployment, db):
            return SimpleNamespace(status=schemas.VerificationStatus.FAIL, summary="error spike",
                                   model_dump=lambda mode=None: {"status": "FAIL", "findings": []})

    async def must_not_send(url, payload, authorization):
        raise AssertionError("auto rollback must not run without SCEPTIC_A2A_AUTO_ROLLBACK=true")

    monkeypatch.setattr(main, "PipelineWatchdog", FakeWatchdog)
    monkeypatch.setattr(a2a, "send_message", must_not_send)

    async with client:
        resp = await client.post(
            "/a2a/watchdog",
            json=a2a.make_request({"deployment_id": str(OWN_DEPLOYMENT)}),
            headers={"Authorization": "Bearer tok-123"},
        )
    data = a2a.response_data(resp.json())
    assert data["rollback"]["status"] == "APPROVAL_REQUIRED"
