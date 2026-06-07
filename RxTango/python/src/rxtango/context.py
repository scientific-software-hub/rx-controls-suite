"""Shared DeviceProxy cache with optional per-device handle caching."""

import atexit

import tango

_atexit_registered = False


class TangoContext:
    """Singleton DeviceProxy cache, shared across the process.

    Use ``TangoContext.get_proxy(device)`` to obtain a cached DeviceProxy.
    Proxies are created lazily on first access; the underlying connection is
    established by PyTango on the first attribute read or command call.

    Call ``TangoContext.close()`` (or let ``atexit`` handle it) to release all
    cached proxies when the process is shutting down.

    Example::

        proxy = TangoContext.get_proxy("tango://localhost:10000/sys/tg_test/1")
        da = proxy.read_attribute("double_scalar")
    """

    _cache: dict[str, tango.DeviceProxy] = {}

    @classmethod
    def get_proxy(cls, device: str) -> tango.DeviceProxy:
        """Return a cached DeviceProxy for *device*, creating it on first access."""
        global _atexit_registered
        if device not in cls._cache:
            cls._cache[device] = tango.DeviceProxy(device)
            if not _atexit_registered:
                atexit.register(cls.close)
                _atexit_registered = True
        return cls._cache[device]

    @classmethod
    def close(cls) -> None:
        """Release all cached DeviceProxy instances."""
        cls._cache.clear()
