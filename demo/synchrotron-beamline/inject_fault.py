"""Inject a storage-ring fault scenario from the command line.

Python equivalent of RxTango/demo/scripts/SetStorageRingScenario.java.
Uses rxtango.write_attribute so the same reactive wrapper is exercised.

Usage
-----
    python inject_fault.py nominal
    python inject_fault.py orbit_drift
    python inject_fault.py vacuum_burst
    python inject_fault.py beam_loss

Prerequisites
-------------
    docker compose up -d --build
"""

import asyncio
import sys
from pathlib import Path

# path bootstrap (facility.py does the heavy lifting, but we need it early)
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import write_attribute
from facility import CONTROLLER, SCENARIO_DESCRIPTIONS as _DESCRIPTIONS, SCENARIOS as _SCENARIOS


async def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _SCENARIOS:
        print("Usage: python inject_fault.py <scenario>")
        print("Scenarios:", " | ".join(_SCENARIOS))
        sys.exit(1)

    scenario_name = sys.argv[1]
    scenario_id   = _SCENARIOS[scenario_name]

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"  → setting scenario: {_DESCRIPTIONS[scenario_id]}")

    write_attribute(CONTROLLER, "ScenarioId", scenario_id).subscribe(
        on_next=lambda v: print(f"  ✓ ScenarioId = {v}  ({scenario_name})"),
        on_error=lambda e: (
            print(f"  ✗ ERROR: {e}", file=sys.stderr),
            done.set(),
        ),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await done.wait()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
