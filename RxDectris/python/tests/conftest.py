"""Shared test fixtures and fakes for rxdectris unit tests.

Mirrors ``RxTango/python/tests/conftest.py``'s style — a hand-written fake
standing in for the real backend — but the backend here is HTTP + a ZeroMQ
socket, so the fake wires an ``httpx.MockTransport`` (real request/response
plumbing, fake network) to a small in-process SIMPLON-shaped state machine,
plus an in-memory queue standing in for the Stream V2 PULL socket.
"""

import asyncio

import cbor2
import httpx
import pytest
from reactivex.scheduler.eventloop import AsyncIOScheduler


# ---------------------------------------------------------------------------
# Fake Stream V2 socket
# ---------------------------------------------------------------------------

class FakeStreamSocket:
    """Stand-in for the zmq.asyncio PULL socket — an asyncio.Queue of CBOR bytes.

    ``push(msg)`` CBOR-encodes *msg* (a dict, same shape a real DCU would
    send) and queues the bytes, so ``recv()`` exercises the same
    ``cbor2.loads`` round trip ``stream.py`` uses against the real socket —
    the fake only replaces the transport, not the wire format.
    """

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()
        self.closed = False

    def push(self, msg: dict) -> None:
        self._queue.put_nowait(cbor2.dumps(msg))

    async def recv(self):
        return await self._queue.get()

    def close(self, linger=0):
        self.closed = True


# ---------------------------------------------------------------------------
# Fake DetectorContext
# ---------------------------------------------------------------------------

class FakeDetectorContext:
    """Test double for ``rxdectris.context.DetectorContext``.

    ``handler(request) -> httpx.Response`` is supplied by the test and drives
    ``self.http`` via ``httpx.MockTransport`` — real ``httpx.AsyncClient``
    request/response objects, no real network. ``stream_socket()`` returns a
    ``FakeStreamSocket`` the test pushes messages into directly.
    """

    def __init__(self, handler) -> None:
        self.base_url = "http://fake-dcu"
        self.http = httpx.AsyncClient(
            base_url=self.base_url, transport=httpx.MockTransport(handler)
        )
        self.stream = FakeStreamSocket()
        self.calls: list[tuple[str, str]] = []  # (method, path) audit trail

    async def stream_socket(self, stream_port=None):
        return self.stream

    async def aclose(self) -> None:
        await self.http.aclose()


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def event_loop_and_scheduler():
    """Return (loop, scheduler) for tests that drive the asyncio event loop."""
    loop = asyncio.new_event_loop()
    scheduler = AsyncIOScheduler(loop)
    yield loop, scheduler
    loop.close()
