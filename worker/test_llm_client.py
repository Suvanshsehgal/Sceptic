import llm_client


def test_daily_quota_error_starts_cooldown():
    llm_client._quota_blocked_until = 0.0
    llm_client.note_llm_error(Exception("Error code: 429 - Rate limit reached ... on tokens per day (TPD): Limit 200000"))
    assert llm_client.llm_blocked() is True
    llm_client._quota_blocked_until = 0.0


def test_per_minute_limit_does_not_start_cooldown():
    llm_client._quota_blocked_until = 0.0
    llm_client.note_llm_error(Exception("Error code: 429 - Rate limit reached on tokens per minute (TPM)"))
    assert llm_client.llm_blocked() is False


def test_other_errors_do_not_start_cooldown():
    llm_client._quota_blocked_until = 0.0
    llm_client.note_llm_error(RuntimeError("no network"))
    assert llm_client.llm_blocked() is False


def test_groq_client_never_retries(monkeypatch):
    captured = {}

    class FakeGroq:
        def __init__(self, api_key, max_retries, timeout):
            captured.update(api_key=api_key, max_retries=max_retries, timeout=timeout)

    import sys
    import types
    fake_module = types.ModuleType("groq")
    fake_module.Groq = FakeGroq
    monkeypatch.setitem(sys.modules, "groq", fake_module)
    llm_client.make_groq_client("k")
    assert captured["max_retries"] == 0
    assert captured["timeout"] == llm_client.REQUEST_TIMEOUT_SECONDS
