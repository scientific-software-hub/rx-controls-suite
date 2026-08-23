"""Shared test fixtures and fakes for rxepics unit tests.

The fakes deliberately reproduce caproto's real asyncio-client contract
(see the resilience design note in ``RxEpics/python/CLAUDE.md``), not a
convenient stand-in for it:

- ``Subscription.add_callback`` stores callbacks by *weakref* and invokes
  them as ``func(sub, response)``.
- ``Subscription.clear()`` is a coroutine.
- ``PV.connection_state_callback.add_callback(func, run=True)`` replays the
  most recent state to a late subscriber, but never fires at all for a PV
  that has not yet connected.

A regression that reintroduces a 1-arg callback, an un-awaited ``clear()``,
or a bare (non-strongly-referenced) closure is caught by these fakes the
same way it would be caught by real caproto.
"""

import subprocess
import sys
import time
import weakref
from pathlib import Path

import pytest
from caproto import CaprotoError
from reactivex.scheduler.eventloop import AsyncIOScheduler


# ---------------------------------------------------------------------------
# Fake CA response objects
# ---------------------------------------------------------------------------

class FakeStatus:
    """Mimics caproto.CAStatusCode: only the .success flag is used by rxepics."""

    def __init__(self, success: bool = True, name: str = "ECA_NORMAL"):
        self.success = success
        self.name = name

    def __repr__(self):
        return self.name


class FakeResponse:
    """Mimics caproto's EventAddResponse: only .data and .status are used."""

    def __init__(self, data, status: FakeStatus | None = None):
        self.data = data
        self.status = status or FakeStatus()


# ---------------------------------------------------------------------------
# Fake CallbackHandler (used for PV.connection_state_callback)
# ---------------------------------------------------------------------------

class FakeCallbackHandler:
    def __init__(self):
        self._callbacks: dict[int, "weakref.ReferenceType"] = {}
        self._next_id = 0
        self._last_state = None

    def add_callback(self, func, run: bool = False) -> int:
        cb_id = self._next_id
        self._next_id += 1
        self._callbacks[cb_id] = weakref.ref(func)
        if run and self._last_state is not None:
            func(None, self._last_state)
        return cb_id

    def remove_callback(self, token: int) -> None:
        self._callbacks.pop(token, None)

    def fire(self, pv, state: str) -> None:
        self._last_state = state
        for ref in list(self._callbacks.values()):
            cb = ref()
            if cb is not None:
                cb(pv, state)


# ---------------------------------------------------------------------------
# Fake Subscription — weakref-backed, 2-arg callback, async clear()
# ---------------------------------------------------------------------------

class FakeSubscription:
    def __init__(self):
        self._callbacks: dict[int, "weakref.ReferenceType"] = {}
        self._next_id = 0
        self.cleared = False

    def add_callback(self, func) -> int:
        cb_id = self._next_id
        self._next_id += 1
        self._callbacks[cb_id] = weakref.ref(func)
        return cb_id

    def remove_callback(self, token: int) -> None:
        self._callbacks.pop(token, None)

    async def clear(self) -> None:
        self.cleared = True
        self._callbacks.clear()

    def fire(self, response: FakeResponse) -> None:
        """Simulate a CA update. Dead (GC'd) weakrefs are dropped, exactly as
        caproto's CallbackHandler.process does."""
        dead = []
        for cb_id, ref in list(self._callbacks.items()):
            cb = ref()
            if cb is None:
                dead.append(cb_id)
                continue
            cb(self, response)
        for cb_id in dead:
            self._callbacks.pop(cb_id, None)

    @property
    def live_callback_count(self) -> int:
        return sum(1 for ref in self._callbacks.values() if ref() is not None)


# ---------------------------------------------------------------------------
# Fake PV / Context
# ---------------------------------------------------------------------------

class FakePV:
    def __init__(self, name: str):
        self.name = name
        self.connection_state_callback = FakeCallbackHandler()
        self._sub: FakeSubscription | None = None

    def subscribe(self, **kwargs) -> FakeSubscription:
        if self._sub is None:
            self._sub = FakeSubscription()
        return self._sub


class FakeContext:
    """Test double for caproto.asyncio.client.Context.

    Use ``fail_lookup.add(name)`` to make ``get_pvs(name)`` raise
    ``CaprotoError``, simulating a PV that cannot be located.
    """

    def __init__(self):
        self.pvs: dict[str, FakePV] = {}
        self.fail_lookup: set[str] = set()

    async def get_pvs(self, *names, **kwargs):
        result = []
        for name in names:
            if name in self.fail_lookup:
                raise CaprotoError(f"cannot locate {name!r}")
            if name not in self.pvs:
                self.pvs[name] = FakePV(name)
            result.append(self.pvs[name])
        return tuple(result)


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_ctx():
    return FakeContext()


@pytest.fixture()
def event_loop_and_scheduler():
    import asyncio
    loop = asyncio.new_event_loop()
    scheduler = AsyncIOScheduler(loop)
    yield loop, scheduler
    loop.close()


# ---------------------------------------------------------------------------
# Real caproto IOC subprocess — integration tests only
# ---------------------------------------------------------------------------

IOC_SCRIPT = Path(__file__).parent / "ioc.py"
IOC_PREFIX = "RXRESIL:"
IOC_PORT = "5099"  # private port; avoids the repo's docker-compose IOC on 5064


class IocProcess:
    """Start/stop/restart the resilience-test IOC as a subprocess."""

    def __init__(self):
        self._proc: subprocess.Popen | None = None

    def start(self) -> None:
        import os
        env = {**os.environ, "EPICS_CA_SERVER_PORT": IOC_PORT}
        self._proc = subprocess.Popen(
            [sys.executable, str(IOC_SCRIPT), "--prefix", IOC_PREFIX],
            env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)  # let the server bind and start serving

    def stop(self) -> None:
        if self._proc is not None:
            self._proc.kill()
            self._proc.wait(timeout=5)
            self._proc = None

    def restart(self) -> None:
        self.stop()
        self.start()


@pytest.fixture()
def ioc():
    proc = IocProcess()
    proc.start()
    yield proc
    proc.stop()
