"""
Synchronous client for the Sceptic MCP tool server.

The server runs as a stdio subprocess (python -m mcp_server). An asyncio loop on a background thread keeps one
session open so synchronous callers (Celery tasks, the CLI, CrewAI tools) can call tools with call_tool().
After a fork (Celery prefork) the thread is not alive in the child, so the client starts its own session there.
"""
import os
import sys
import asyncio
import atexit
import logging
import threading
from typing import Any, Dict, Optional

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

logger = logging.getLogger("sceptic.mcp_client")

WORKER_DIR = os.path.dirname(os.path.abspath(__file__))
STARTUP_TIMEOUT_SECONDS = 120
DEFAULT_CALL_TIMEOUT_SECONDS = 600


class MCPToolError(RuntimeError):
    """A tool call failed or the tool server could not be started."""


class SceptiMCPClient:
    def __init__(self):
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._thread: Optional[threading.Thread] = None
        self._session: Optional[ClientSession] = None
        self._stop_event: Optional[asyncio.Event] = None
        self._startup_error: Optional[BaseException] = None

    def _is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive() and self._session is not None

    def _ensure_started(self) -> None:
        with self._lock:
            if self._is_running():
                return
            self._startup_error = None
            self._session = None
            self._loop = asyncio.new_event_loop()
            ready = threading.Event()
            self._thread = threading.Thread(target=self._run_loop, args=(ready,), name="sceptic-mcp", daemon=True)
            self._thread.start()
            if not ready.wait(timeout=STARTUP_TIMEOUT_SECONDS) or self._session is None:
                error = self._startup_error or TimeoutError("tool server did not start in time")
                raise MCPToolError(f"Sceptic tool server failed to start: {error}")

    def _run_loop(self, ready: threading.Event) -> None:
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve(ready))
        finally:
            ready.set()
            self._loop.close()

    async def _serve(self, ready: threading.Event) -> None:
        params = StdioServerParameters(
            command=sys.executable,
            args=["-m", "mcp_server"],
            cwd=WORKER_DIR,
            env=dict(os.environ),
        )
        try:
            async with stdio_client(params) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    self._stop_event = asyncio.Event()
                    self._session = session
                    ready.set()
                    await self._stop_event.wait()
        except BaseException as e:  # startup or transport failure
            self._startup_error = e
            self._session = None
            ready.set()

    def call_tool(self, name: str, arguments: Dict[str, Any], timeout: float = DEFAULT_CALL_TIMEOUT_SECONDS) -> str:
        """Calls an MCP tool and returns its text output. Raises MCPToolError on any failure."""
        self._ensure_started()
        session = self._session
        loop = self._loop
        try:
            future = asyncio.run_coroutine_threadsafe(session.call_tool(name, arguments), loop)
            result = future.result(timeout=timeout)
        except Exception as e:
            self._session = None
            raise MCPToolError(f"Tool '{name}' failed: {e}") from e

        text = "".join(
            getattr(item, "text", "") for item in result.content if getattr(item, "type", None) == "text"
        )
        if result.isError:
            raise MCPToolError(f"Tool '{name}' returned an error: {text}")
        return text

    def shutdown(self) -> None:
        if self._is_running() and self._stop_event is not None and self._loop is not None:
            self._loop.call_soon_threadsafe(self._stop_event.set)
            self._thread.join(timeout=10)
        self._session = None


_client: Optional[SceptiMCPClient] = None
_client_lock = threading.Lock()


def get_mcp_client() -> SceptiMCPClient:
    global _client
    with _client_lock:
        if _client is None:
            _client = SceptiMCPClient()
        return _client


@atexit.register
def _shutdown_client() -> None:
    if _client is not None:
        _client.shutdown()
