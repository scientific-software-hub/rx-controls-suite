"""Shared fakes for demo/dectris-integration's mock-only test suite.

No live simulator, no docker stack, no network — same policy as
RxDectris/python/tests/conftest.py (whose FakeDetectorContext this mirrors;
duplicated rather than imported because test fixtures aren't meant to be a
reusable library surface across packages).
"""

import asyncio
import sys
from pathlib import Path

import cbor2
import httpx
import pytest
from reactivex.scheduler.eventloop import AsyncIOScheduler

_ROOT = Path(__file__).resolve().parent.parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxDectris" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "demo" / "dectris-integration"))


class FakeStreamSocket:
    """Stand-in for the zmq.asyncio PULL socket — see RxDectris's own fake."""

    def __init__(self) -> None:
        self._queue: asyncio.Queue = asyncio.Queue()

    def push(self, msg: dict) -> None:
        self._queue.put_nowait(cbor2.dumps(msg))

    async def recv(self):
        return await self._queue.get()

    def close(self, linger=0):
        pass


class FakeDetectorContext:
    """Test double for ``rxdectris.context.DetectorContext``."""

    def __init__(self, handler) -> None:
        self.base_url = "http://fake-dcu"
        self.http = httpx.AsyncClient(base_url=self.base_url, transport=httpx.MockTransport(handler))
        self.stream = FakeStreamSocket()

    async def stream_socket(self, stream_port=None):
        return self.stream

    async def aclose(self) -> None:
        await self.http.aclose()


class FakeDlabContext:
    """Test double for ``dlab.DlabContext``."""

    def __init__(self, handler) -> None:
        self.base_url = "http://fake-dlab"
        self.http = httpx.AsyncClient(base_url=self.base_url, transport=httpx.MockTransport(handler))

    async def aclose(self) -> None:
        await self.http.aclose()


@pytest.fixture()
def event_loop_and_scheduler():
    loop = asyncio.new_event_loop()
    scheduler = AsyncIOScheduler(loop)
    yield loop, scheduler
    loop.close()
