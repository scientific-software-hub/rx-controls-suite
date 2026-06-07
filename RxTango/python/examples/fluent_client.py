"""TangoClient fluent builder — one-liners for common patterns.

Demonstrates the TangoClient API: read, map, write, execute.

Mirrors `FluentClient.java`.

Usage:
    python fluent_client.py [device]

    device  defaults to tango://localhost:10000/sys/tg_test/1
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from reactivex.scheduler.eventloop import AsyncIOScheduler

from rxtango import TangoClient


async def main() -> None:
    device = sys.argv[1] if len(sys.argv) > 1 else "tango://localhost:10000/sys/tg_test/1"

    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)

    # ── Demo 1: read → map → write ────────────────────────────────────────
    print("Demo 1: read → negate → write\n")
    done1 = asyncio.Event()

    TangoClient() \
        .read(device, "double_scalar") \
        .write(device, "double_scalar_w", value=lambda v: -v) \
        .subscribe(
            on_next=lambda v: print(f"  written: {v:+.6f}"),
            on_completed=lambda: (print("  done.\n"), done1.set()),
            on_error=lambda e: (print(f"  ERROR: {e}"), done1.set()),
            scheduler=scheduler,
        )

    await asyncio.wait_for(done1.wait(), timeout=5.0)

    # ── Demo 2: execute command → read result ─────────────────────────────
    print("Demo 2: execute State command → print\n")
    done2 = asyncio.Event()

    TangoClient() \
        .execute(device, "State") \
        .subscribe(
            on_next=lambda v: print(f"  State = {v}"),
            on_completed=lambda: (print("  done.\n"), done2.set()),
            on_error=lambda e: (print(f"  ERROR: {e}"), done2.set()),
            scheduler=scheduler,
        )

    await asyncio.wait_for(done2.wait(), timeout=5.0)

    # ── Demo 3: multi-step chain ───────────────────────────────────────────
    print("Demo 3: read → calibrate → write → read-back\n")
    done3 = asyncio.Event()

    TangoClient() \
        .read(device, "double_scalar") \
        .map(lambda v: abs(v) * 2.0 + 1.5) \
        .write(device, "double_scalar_w") \
        .read(device, "double_scalar_w") \
        .subscribe(
            on_next=lambda v: print(f"  read-back: {v:+.6f}"),
            on_completed=lambda: (print("  done."), done3.set()),
            on_error=lambda e: (print(f"  ERROR: {e}"), done3.set()),
            scheduler=scheduler,
        )

    await asyncio.wait_for(done3.wait(), timeout=5.0)


if __name__ == "__main__":
    asyncio.run(main())
