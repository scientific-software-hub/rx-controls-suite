"""Inject any of the demo's four fault families from one command.

Usage:
    python inject_fault.py nominal              # resets ring + detector + D.LAB
    python inject_fault.py beam_loss
    python inject_fault.py orbit_drift
    python inject_fault.py vacuum_burst
    python inject_fault.py detector_error        # next detector trigger fails
    python inject_fault.py flaky_processing      # next 2 D.LAB jobs fail, then recover
    python inject_fault.py processing_failure    # every new D.LAB job fails

Ring scenarios go through rxtango.write_attribute — same mechanism as
demo/synchrotron-beamline/inject_fault.py, unchanged. Detector and D.LAB
faults are demo-only ``/_sim/fault`` endpoints (see simplon_sim/app.py,
dlab_sim/app.py) — namespaced so nothing here shadows a real SIMPLON or
D.LAB path.
"""

import asyncio
import sys
from pathlib import Path

import httpx

_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler  # noqa: E402
from rxtango import write_attribute  # noqa: E402

CONTROLLER = "tango://localhost:10000/sr/demo/controller"
SIMPLON_URL = "http://localhost:8080"
DLAB_URL = "http://localhost:8090"

_RING_SCENARIOS = {"nominal": 0, "orbit_drift": 1, "vacuum_burst": 2, "beam_loss": 3}
_ALL_FAULTS = (*_RING_SCENARIOS, "detector_error", "flaky_processing", "processing_failure")


async def _set_ring_scenario(scenario_id: int) -> None:
    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()
    write_attribute(CONTROLLER, "ScenarioId", scenario_id).subscribe(
        on_error=lambda e: (print(f"  ring ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )
    await done.wait()


async def _put_fault(base_url: str, value: str) -> None:
    async with httpx.AsyncClient(base_url=base_url, timeout=5.0) as client:
        resp = await client.put("/_sim/fault", json={"value": value})
        resp.raise_for_status()


async def main() -> None:
    if len(sys.argv) < 2 or sys.argv[1] not in _ALL_FAULTS:
        print(__doc__)
        sys.exit(0 if len(sys.argv) < 2 else 1)

    fault = sys.argv[1]

    if fault == "nominal":
        await _set_ring_scenario(0)
        await _put_fault(SIMPLON_URL, "nominal")
        await _put_fault(DLAB_URL, "nominal")
        print("  -> nominal: ring + detector + D.LAB all reset")
    elif fault in _RING_SCENARIOS:
        await _set_ring_scenario(_RING_SCENARIOS[fault])
        print(f"  -> ring scenario: {fault}")
    elif fault == "detector_error":
        await _put_fault(SIMPLON_URL, "detector_error")
        print("  -> the next detector trigger will fail")
    elif fault == "processing_failure":
        await _put_fault(DLAB_URL, "processing_failure")
        print("  -> every new D.LAB job will fail until reset")
    elif fault == "flaky_processing":
        await _put_fault(DLAB_URL, "flaky:2")
        print("  -> the next 2 D.LAB job submissions fail, then recover")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
