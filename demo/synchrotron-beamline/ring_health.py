"""Live storage-ring health dashboard — intro script.

Connects to the Tango storage-ring simulator and continuously prints a
Health snapshot: beam current, interlock count, and representative orbit
deviation from sector 04.

Run this *before* guarded_scan.py to understand the ring state.
Inject faults in a second terminal with inject_fault.py to watch the
health stream respond in real time.

Usage
-----
    python ring_health.py [interval_ms]

    interval_ms  defaults to 1000

Prerequisites
-------------
    docker compose up -d --build
    # (in a second terminal)
    python inject_fault.py orbit_drift
    python inject_fault.py nominal
"""

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))

import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from facility import ring_health, is_healthy, MIN_BEAM_CURRENT, ORBIT_ALARM


def _status(h) -> str:
    if h.interlocks > 0:
        return f"\033[31m⛔ INTERLOCK ({int(h.interlocks)} active)\033[0m"
    if h.current < MIN_BEAM_CURRENT:
        return "\033[33m⚠  BEAM LOW — acquisition paused\033[0m"
    if abs(h.orbit_x) >= ORBIT_ALARM:
        return "\033[33m~  ORBIT ALARM — frames flagged low-quality\033[0m"
    return "\033[32m✓  healthy\033[0m"


async def main() -> None:
    interval_ms = int(sys.argv[1]) if len(sys.argv) > 1 else 1000

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    print()
    print("  Storage Ring Health Monitor")
    print("  " + "=" * 60)
    print(f"  {'current (mA)':>14}  {'interlocks':>12}  {'orbitX (µm)':>12}  status")
    print("  " + "-" * 60)

    ring_health(scheduler, interval_ms).subscribe(
        on_next=lambda h: print(
            f"\r  {h.current:>+14.2f}  {int(h.interlocks):>12d}  {h.orbit_x:>+12.1f}  {_status(h)}",
            flush=True,
        ),
        on_error=lambda e: print(f"\n  ERROR: {e}", file=sys.stderr),
        scheduler=scheduler,
    )

    await asyncio.Future()  # run until Ctrl+C


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n  stopped.")
