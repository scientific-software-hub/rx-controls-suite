"""The RxDECTRIS hero pipeline.

    python experiment.py --facility epics --frames 100 --count-time 0.01
    python experiment.py --facility tango --frames 100 --count-time 0.01

The reveal: only ``--facility`` and the ``Facility()`` constructor call below
differ between the two runs. Everything else — the gate, the acquisition,
the per-frame correlation, the HDF5 write, the D.LAB stage, the validation —
is the same code path, because it never touches EPICS or Tango directly. It
only ever talks to a ``Facility`` (facility.py's ``Protocol``).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import reactivex as rx
from caproto.asyncio.client import Context as EpicsContext
from reactivex.scheduler.eventloop import AsyncIOScheduler

from dlab import DlabContext, RxDlab
from facilities import EpicsFacility, TangoFacility
from recipes import (
    AcquiredFrame,
    AcquisitionRun,
    correlate_with,
    guarded_by,
    process_with,
    validate_result,
    wait_until_healthy,
)
from rxdectris import DetectorContext, acquire_series
from rxdectris.command import initialize
from rxdectris.models import SeriesEnd, SeriesStart


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--facility", choices=("epics", "tango"), required=True)
    parser.add_argument("--frames", type=int, default=100)
    parser.add_argument("--count-time", type=float, default=0.01)
    parser.add_argument("--simplon-url", default="http://localhost:8080")
    parser.add_argument("--dlab-url", default="http://localhost:8090")
    parser.add_argument("--workflow", default="demo-processing")
    parser.add_argument("--out-dir", default=str(Path(__file__).resolve().parent))
    args = parser.parse_args()

    loop = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done = asyncio.Event()

    detector_ctx = await DetectorContext.get(args.simplon_url)

    if args.facility == "tango":
        facility = TangoFacility(scheduler)
    else:
        epics_ctx = EpicsContext()
        facility = EpicsFacility(epics_ctx, scheduler)

    dlab_ctx = DlabContext(args.dlab_url)
    dlab = RxDlab(dlab_ctx)

    print(f"facility={facility.name}  frames={args.frames}  count_time={args.count_time}s")

    initialize(detector_ctx).subscribe(
        on_error=lambda e: print(f"initialize: {e}", file=sys.stderr), scheduler=scheduler
    )
    await asyncio.sleep(0.2)

    run = AcquisitionRun(Path(args.out_dir), num_frames=args.frames, facility_source=facility.name)

    def on_next(msg):
        if isinstance(msg, AcquiredFrame):
            run.write_frame(msg)
            flag = "OK" if msg.quality_ok else "BAD"
            print(f"  frame {msg.frame.image_id:4d}  counts={msg.frame.counts:8.0f}  quality={flag}")
        elif isinstance(msg, SeriesStart):
            print(f"  start   series={msg.series_id}  n={msg.number_of_images}")
        elif isinstance(msg, SeriesEnd):
            print(f"  end     series={msg.series_id}")

    def start_processing():
        summary = run.summary()
        print(f"acquisition complete: {summary['frames']} frames, {summary['quality_ok']} quality-ok")
        print(f"  uploading -> D.LAB workflow={args.workflow!r} ...")
        rx.of(summary).pipe(
            process_with(dlab, args.workflow, retries=3),
            validate_result(),
        ).subscribe(
            on_next=lambda r: print(f"  processing: {r['status']}  result={r.get('result')}"),
            on_error=lambda e: (print(f"  processing FAILED: {e}", file=sys.stderr), done.set()),
            on_completed=done.set,
            scheduler=scheduler,
        )

    def on_completed():
        run.close()
        if run.frames_written < args.frames:
            print(f"  ABORTED — {run.frames_written}/{args.frames} frames written (facility interlock)")
            done.set()
            return
        start_processing()

    def on_error(exc):
        print(f"  ERROR: {exc}", file=sys.stderr)
        run.close()
        done.set()

    experiment = rx.concat(
        wait_until_healthy(facility.health()),
        acquire_series(detector_ctx, frames=args.frames, count_time=args.count_time),
    ).pipe(
        guarded_by(facility.health(), detector_ctx),
        correlate_with(facility),
    )

    experiment.subscribe(on_next=on_next, on_error=on_error, on_completed=on_completed, scheduler=scheduler)

    await done.wait()
    await detector_ctx.aclose()
    await dlab_ctx.aclose()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
