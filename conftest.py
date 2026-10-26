import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "worker"))


@pytest.fixture(autouse=True)
def _reset_llm_quota_cooldown():
    # A daily-quota cooldown from one test must not make the next test skip its LLM path.
    import llm_client
    llm_client._quota_blocked_until = 0.0
    yield
    llm_client._quota_blocked_until = 0.0


# The unit suite runs generated tests on the host so it works without Docker.
# Production and CI sandbox behavior is covered by worker/test_sandbox_runner.py, which selects docker explicitly.
os.environ.setdefault("SCEPTIC_SANDBOX", "local-unsafe")
