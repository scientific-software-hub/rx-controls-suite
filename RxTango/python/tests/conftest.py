"""Shared test fixtures and fakes for rxtango unit tests."""

import asyncio
from unittest.mock import MagicMock

import pytest
from reactivex.scheduler.eventloop import AsyncIOScheduler


# ---------------------------------------------------------------------------
# Fake Tango data objects
# ---------------------------------------------------------------------------

class FakeAttrValue:
    """Minimal DeviceAttribute value mock."""
    def __init__(self, value):
        self.value = value


class FakeEventData:
    """Minimal EventData mock for monitor tests."""
    def __init__(self, value):
        self.attr_value = FakeAttrValue(value)
        self.err = False


# ---------------------------------------------------------------------------
# FakeDeviceProxy
# ---------------------------------------------------------------------------

class FakeDeviceProxy:
    """Test double for tango.DeviceProxy.

    Provides controllable implementations of all DeviceProxy methods used by
    rxtango:

    - ``read_attribute(name)``   → returns a FakeAttrValue wrapping ``read_value``
    - ``write_attribute(name, value)`` → records the written value
    - ``command_inout(name[, argin])`` → returns ``command_result``
    - ``subscribe_event(attr, evt_type, callback)`` → stores callback; returns 1
    - ``unsubscribe_event(event_id)`` → records the id in ``unsubscribed``

    Use ``fire(value)`` to simulate a Tango event callback from the device.
    """

    def __init__(self, read_value=0.0, command_result=None):
        self._read_value = read_value
        self._command_result = command_result
        self._written: list = []
        self._event_callback = None
        self.unsubscribed: list[int] = []
        self._next_event_id = 1

    # ---- attribute read ---------------------------------------------------

    def read_attribute(self, name: str):
        attr = MagicMock()
        attr.value = self._read_value
        return attr

    # ---- attribute write --------------------------------------------------

    def write_attribute(self, name: str, value):
        self._written.append((name, value))

    # ---- command ----------------------------------------------------------

    def command_inout(self, name: str, argin=None):
        return self._command_result

    # ---- events -----------------------------------------------------------

    def subscribe_event(self, attr_name: str, event_type, callback) -> int:
        self._event_callback = callback
        event_id = self._next_event_id
        self._next_event_id += 1
        return event_id

    def unsubscribe_event(self, event_id: int) -> None:
        self.unsubscribed.append(event_id)

    def fire(self, value) -> None:
        """Simulate a Tango event arriving from a device (calls stored callback)."""
        if self._event_callback is not None:
            self._event_callback(FakeEventData(value))


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def fake_proxy():
    """Return a fresh FakeDeviceProxy with read_value=42.0."""
    return FakeDeviceProxy(read_value=42.0)


@pytest.fixture()
def event_loop_and_scheduler():
    """Return (loop, scheduler) for tests that drive the asyncio event loop."""
    loop = asyncio.new_event_loop()
    scheduler = AsyncIOScheduler(loop)
    yield loop, scheduler
    loop.close()
