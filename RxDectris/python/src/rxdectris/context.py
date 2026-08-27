"""Shared per-DCU connection cache — HTTP client + Stream V2 ZeroMQ socket."""

from __future__ import annotations

import atexit
from urllib.parse import urlsplit

import httpx
import zmq
import zmq.asyncio

#: SIMPLON API version this wrapper is written against.
API_VERSION = "1.8.0"

#: Stream V2 default port (ZeroMQ PUSH on the DCU, PULL here). See SIMPLON
#: 1.8 API documentation §5.4.2, Table 5.17.
STREAM_PORT = 31001


class DetectorContext:
    """Singleton connection cache, one per DCU base URL.

    Use ``await DetectorContext.get(base_url)`` to obtain the shared context.
    Mirrors ``TangoContext.get_proxy(device)`` / ``EpicsContext.get()`` — the
    locator the tests patch is this classmethod, not the constructor.
    """

    _cache: dict[str, "DetectorContext"] = {}
    _atexit_registered = False

    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(base_url=self.base_url, timeout=10.0)
        self._zmq_ctx: zmq.asyncio.Context | None = None
        self._pull_socket: zmq.asyncio.Socket | None = None

    @classmethod
    async def get(cls, base_url: str) -> "DetectorContext":
        """Return the shared :class:`DetectorContext` for *base_url*, creating it on first access."""
        if base_url not in cls._cache:
            cls._cache[base_url] = cls(base_url)
            if not cls._atexit_registered:
                atexit.register(cls.close_all)
                cls._atexit_registered = True
        return cls._cache[base_url]

    async def stream_socket(self, stream_port: int = STREAM_PORT) -> zmq.asyncio.Socket:
        """Return the lazily-connected Stream V2 PULL socket for this DCU."""
        if self._pull_socket is None:
            host = urlsplit(self.base_url).hostname or "127.0.0.1"
            self._zmq_ctx = zmq.asyncio.Context.instance()
            sock = self._zmq_ctx.socket(zmq.PULL)
            sock.connect(f"tcp://{host}:{stream_port}")
            self._pull_socket = sock
        return self._pull_socket

    async def aclose(self) -> None:
        """Release this context's HTTP client and stream socket."""
        await self.http.aclose()
        if self._pull_socket is not None:
            self._pull_socket.close(linger=0)
            self._pull_socket = None

    @classmethod
    def close_all(cls) -> None:
        """Drop all cached contexts. Best-effort — does not await socket teardown."""
        cls._cache.clear()
