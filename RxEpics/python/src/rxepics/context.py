"""Shared caproto async Context with optional PV handle cache."""

import atexit

from caproto.asyncio.client import Context


class EpicsContext:
    """Singleton caproto Context, shared across the process.

    Use ``await EpicsContext.get()`` to obtain the shared Context.
    Use ``await EpicsContext.get_pv(name)`` to obtain a cached PV handle.

    Call ``EpicsContext.close()`` (or let ``atexit`` handle it) to release
    the Context when the process is shutting down.
    """

    _ctx: Context | None = None
    _cache: dict = {}

    @classmethod
    async def get(cls) -> Context:
        """Return the shared Context, creating it on first call."""
        if cls._ctx is None:
            cls._ctx = Context()
            atexit.register(cls.close)
        return cls._ctx

    @classmethod
    async def get_pv(cls, name: str):
        """Return a cached PV handle, locating it on first access."""
        if name not in cls._cache:
            ctx = await cls.get()
            (pv,) = await ctx.get_pvs(name)
            cls._cache[name] = pv
        return cls._cache[name]

    @classmethod
    def close(cls) -> None:
        """Release the shared Context and clear the PV cache."""
        cls._cache.clear()
        cls._ctx = None
