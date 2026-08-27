"""Mirror the Tango storage ring into EPICS FAC:* PVs, at 2 Hz.

Why this exists: EpicsFacility (facility.py) needs an EPICS-native way to see
the same simulated ring TangoFacility already sees directly — the tomography
IOC has no interlock/orbit records of its own, and there's no EPICS gateway
in front of the Tango stack in this demo. This script is that gateway, in
~40 lines of the suite's own idiom: read the Tango ring
(demo/synchrotron-beamline/facility.py::ring_health, unmodified) and write
it into RxEpics/python/demo/tomography/tomography.db's FAC:* records.

Run this alongside the stack before `experiment.py --facility epics`:

    docker compose up -d
    python facility_bridge.py &
    python experiment.py --facility epics

Prerequisites: same as demo/synchrotron-beamline/inject_fault.py —
EPICS_CA_AUTO_ADDR_LIST=NO, EPICS_CA_ADDR_LIST=127.0.0.1 (host-networked IOC).
"""

import asyncio
import sys
from pathlib import Path

# path bootstrap — reuse the sibling demo's facility.py, no duplication
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "demo" / "synchrotron-beamline"))

import reactivex as rx
import reactivex.operators as ops
from caproto.asyncio.client import Context
from reactivex.scheduler.eventloop import AsyncIOScheduler

from facility import is_healthy, ring_health  # noqa: E402  -- synchrotron-beamline's
from rxepics.channel_write import write_pv  # noqa: E402


async def main() -> None:
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    ctx = Context()

    print("facility_bridge: mirroring Tango ring -> FAC:* PVs at 2 Hz (Ctrl-C to stop)")

    def mirror(h) -> rx.Observable:
        return rx.zip(
            write_pv("FAC:CURRENT", h.current, ctx),
            write_pv("FAC:INTERLOCK", h.interlocks, ctx),
            write_pv("FAC:ORBIT_X", h.orbit_x, ctx),
            write_pv("FAC:BEAM_OK", 1 if is_healthy(h) else 0, ctx),
        )

    ring_health(scheduler, interval_ms=500).pipe(
        ops.flat_map(mirror),
    ).subscribe(
        on_next=lambda _: None,
        on_error=lambda e: print(f"facility_bridge ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Event().wait()  # run forever — stop with Ctrl-C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
