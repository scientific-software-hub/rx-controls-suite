"""Read → calibrate → write pipeline (one shot).

Reads `double_scalar`, applies a linear calibration, writes the result to
`double_scalar_w`, formats it as a string, and writes to `string_scalar_w`.

Mirrors `CalibrationPipeline.java`.

Usage:
    python calibration_pipeline.py [device]

    device  defaults to tango://localhost:10000/sys/tg_test/1
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import read_attribute, write_attribute


async def main() -> None:
    device = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    print(f"Calibration pipeline on {device}\n")

    read_attribute(device, "double_scalar").pipe(
        ops.do_action(on_next=lambda v: print(f"  [1] read    double_scalar  = {v:+.6f}")),

        # Linear calibration: y = |x| * 2.0 + 1.5
        ops.map(lambda v: abs(v) * 2.0 + 1.5),
        ops.do_action(on_next=lambda v: print(f"  [2] calibrated             = {v:+.6f}")),

        # Write calibrated value
        ops.flat_map(lambda v: write_attribute(device, "double_scalar_w", v)),
        ops.do_action(on_next=lambda v: print(f"  [3] wrote   double_scalar_w = {v:+.6f}")),

        # Format as string
        ops.map(lambda v: f"cal={v:.4f}"),
        ops.do_action(on_next=lambda s: print(f"  [4] formatted              = {s!r}")),

        # Write string (write_attribute works for any type PyTango accepts)
        ops.flat_map(lambda s: write_attribute(device, "string_scalar_w", s)),
        ops.do_action(on_next=lambda s: print(f"  [5] wrote   string_scalar_w = {s!r}")),

    ).subscribe(
        on_next=lambda _: None,
        on_error=lambda e: (print(f"  ERROR: {e}", file=sys.stderr), done.set()),
        on_completed=done.set,
        scheduler=scheduler,
    )

    await asyncio.wait_for(done.wait(), timeout=10.0)
    print("\n  Pipeline complete.")


if __name__ == "__main__":
    asyncio.run(main())
