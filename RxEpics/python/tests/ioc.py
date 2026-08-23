#!/usr/bin/env python3
"""Minimal caproto IOC for the resilience integration test.

A fast-updating float (``x``, ~5 Hz) and a static string (``label``). Not
used by unit tests — those run against the fakes in conftest.py. Only
``test_resilience_ioc.py`` (marked ``integration``) spawns this as a
subprocess so it can be killed and restarted to prove reconnect behavior.
"""
from textwrap import dedent

import random

from caproto.server import PVGroup, ioc_arg_parser, pvproperty, run


class ResilienceIOC(PVGroup):
    """A fast-updating float ``x`` and a static string ``label``."""

    x = pvproperty(value=0.0, doc="Fast-updating float")
    label = pvproperty(value="idle", doc="Static string", string_encoding="utf-8")

    @x.startup
    async def x(self, instance, async_lib):
        while True:
            await instance.write(value=random.uniform(-1.0, 1.0))
            await async_lib.sleep(0.2)


if __name__ == "__main__":
    ioc_options, run_options = ioc_arg_parser(
        default_prefix="RXRESIL:", desc=dedent(ResilienceIOC.__doc__)
    )
    ioc = ResilienceIOC(**ioc_options)
    run(ioc.pvdb, **run_options)
