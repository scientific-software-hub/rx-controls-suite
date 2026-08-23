"""End-to-end proof against a real caproto IOC: values flow, the IOC is
killed, connection_status reports the disconnect, the IOC is restarted, and
both connection_status and monitor_pv resume — without any client-side
action. This is the reconnect claim from the design note, proven rather than
assumed.

Slow (~30-60s, dominated by caproto's CA search retry backoff after the IOC
returns). Run explicitly with: pytest -m integration
"""

import asyncio
import os

import pytest
from caproto.asyncio.client import Context
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxepics.connection import connection_status
from rxepics.monitor import monitor_pv
from conftest import IOC_PORT, IOC_PREFIX

pytestmark = pytest.mark.integration


async def _wait_until(predicate, timeout: float, interval: float = 0.5):
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()


def test_monitor_and_connection_status_survive_ioc_restart(ioc):
    pv_name = f"{IOC_PREFIX}x"

    async def run():
        os.environ["EPICS_CA_SERVER_PORT"] = IOC_PORT
        os.environ["EPICS_CA_ADDR_LIST"] = "127.0.0.1"
        os.environ["EPICS_CA_AUTO_ADDR_LIST"] = "NO"

        loop = asyncio.get_running_loop()
        scheduler = AsyncIOScheduler(loop)
        ctx = Context()

        values = []
        states = []
        monitor_pv(pv_name, ctx).subscribe(on_next=values.append, scheduler=scheduler)
        connection_status(pv_name, ctx).subscribe(on_next=states.append, scheduler=scheduler)

        assert await _wait_until(lambda: len(values) >= 1, timeout=10), (
            "no initial values received"
        )
        assert states[-1] is True, "expected connected before IOC restart"

        n_before = len(values)
        ioc.stop()

        assert await _wait_until(lambda: states[-1] is False, timeout=15), (
            f"connection_status never reported disconnect: {states}"
        )

        ioc.start()

        assert await _wait_until(lambda: states[-1] is True, timeout=30), (
            f"connection_status never reported reconnect: {states}"
        )
        assert await _wait_until(lambda: len(values) > n_before, timeout=30), (
            "monitor_pv did not resume emitting values after IOC restart"
        )

        await ctx.disconnect()

    asyncio.run(run())
