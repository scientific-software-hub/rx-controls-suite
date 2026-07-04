# Bluesky × rx-controls-suite — Guarded Scan

The [pure-rx guarded scan](../guarded_scan.py), re-orchestrated by a
[Bluesky](https://blueskyproject.io) RunEngine. The point is positioning:
**rx-controls-suite does not compete with Bluesky — it feeds it.**

Bluesky owns what it is best at: plans, Event documents, metadata,
suspend/resume with checkpoint rewind, clean aborts. The rx wrappers own
what Bluesky does not have: a uniform reactive vocabulary across control
systems — here, the **Tango** storage ring, which stock Bluesky/ophyd
(EPICS-native) cannot see.

```
        Bluesky RunEngine                     rx-controls-suite
  ┌─────────────────────────────┐      ┌──────────────────────────────────┐
  │ bp.scan([det, ring], motor) │      │ ring_health  (1 Hz Tango stream) │
  │ suspend / rewind / abort    │◀────▶│ device verbs (write→poll→done)   │
  │ Event documents             │      │ document fan-out (HDF5 vs live)  │
  └─────────────────────────────┘      └──────────────────────────────────┘
                     four seams, ~40 lines each:
       RxStatus · RxSignal · rx_wait · documents   (rx_bluesky.py)
```

## The four bridges (`rx_bluesky.py`)

| Bridge | Direction | Bluesky concept | Backed by |
|---|---|---|---|
| `RxStatus` | rx → Bluesky | `Status` (set/trigger done) | any Observable's `on_completed` |
| `RxSignal` | rx → Bluesky | suspender input signal | any Observable's emissions |
| `rx_wait` | rx → Bluesky | blocking `read()` | first emission of a pipeline |
| `documents` | Bluesky → rx | document subscriber | `Subject` of `(name, doc)` |

`devices.py` then implements the Bluesky protocols (Readable / Movable /
Triggerable) directly on rxepics/rxtango pipelines — **no ophyd, no
pyepics**. `motor.set(angle)` *is* `write_pv(ROT:VAL) → poll MOVN==0`,
wrapped in an `RxStatus`.

## The four fault patterns, re-mapped

| Pattern | Pure-rx demo | Bluesky demo |
|---|---|---|
| Beam-loss recovery | `filter(is_healthy) + take(1)` gate per projection | `SuspendBoolLow(RxSignal(beam_ok))` — Tango health stream trips a Bluesky suspender; `pre_plan`/`post_plan` close and re-open the shutter; the RunEngine rewinds to the last checkpoint and re-takes the step |
| Orbit-drift quality | cross-system `rx.zip` per frame | `RingHealth` is a Readable in the detector list — every Event document carries Tango `ring_current`, `orbit_x`, `quality_ok` next to EPICS `counts` |
| Vacuum-burst abort | `take_until(abort_trigger)` | interlock stream → `RE.request_pause()` → `RE.abort()`; documents end with `exit_status='abort'` |
| Backpressure | `share()` + `sample()` | RunEngine documents come *back* into rx: HDF5 subscribes raw (every event), the display through `sample(display_ms)` |

The scan-state PVs are mirrored from the document stream, so the existing
[web dashboard](../live_dashboard.py) tracks a Bluesky scan without any change.

## Run it

```bash
# stack + venv as in ../README.md, plus:
uv pip install bluesky

cd demo/synchrotron-beamline/bluesky
# 36 projections, 0–180°
python guarded_scan_bluesky.py

# in a second terminal:
python ../inject_fault.py beam_loss      # suspender trips, shutter closes
python ../inject_fault.py nominal        # resumes, interrupted step re-taken
python ../inject_fault.py orbit_drift    # quality_ok=False in the documents
python ../inject_fault.py vacuum_burst   # RE.abort, exit_status='abort'
```

Expected output during a beam-loss cycle — note that this is *Bluesky's own*
suspension machinery, driven by a Tango stream it could not otherwise watch:

```
Suspending....To get prompt hit Ctrl-C twice to pause.
Justification for this suspension:
Signal beam_ok is low: storage-ring beam below 50 mA
Suspender SuspendBoolLow(RxSignal('beam_ok'), ...) reports a return to
nominal conditions. Will sleep for 1.0 seconds and then release suspension.
```

## Live strip chart (for demos & screen recordings)

`live_strip.py` + `strip.html` — a single sliding-window instrument panel:
beam-current trace (5 Hz, Tango via rxtango), 50 mA gate, amber suspension
bands with the suspend/release annotations, and an event-document tick lane.
State chips show RUNNING / SUSPENDED / ABORTED / DONE live. Derived entirely
from the mirrored scan-state PVs, so it works under both the pure-rx and the
Bluesky scan without touching the scan process.

```bash
# stack + EPICS_CA_* exports as above, then:
uv run --with fastapi --with "uvicorn[standard]" python live_strip.py
# open http://127.0.0.1:8010   (STRIP_HOST / STRIP_PORT override)
```

## Threading model

`rxepics`/`rxtango` schedule work with `asyncio.ensure_future`, so all rx
subscriptions live on a dedicated loop thread (`RxLoop`). The RunEngine runs
its own loop. The bridges cross between the two exclusively with
`call_soon_threadsafe` — neither loop ever blocks on the other. The one
subtlety: suspender callbacks fan out on a private worker thread, because
`SuspenderBase` briefly blocks its calling thread while the rx loop must stay
free to serve device reads.

## BLISS mapping (design sketch)

BLISS (ESRF; slated for PETRA IV) is the same story with different seam names.
It is not included as a runnable demo because BLISS requires its full server
stack (Beacon + Redis + session infrastructure), which doesn't reduce to a
`pip install` against this docker-compose setup. The mapping:

| This demo (Bluesky) | BLISS equivalent |
|---|---|
| `RxStatus` from a device verb | BLISS controllers are gevent-based and blocking — wrap the rx pipeline with `rx_wait` inside a custom `Controller`/`Axis` |
| `SuspendBoolLow(RxSignal(...))` | `ScanPreset` hooks (`prepare`/`start`/`stop`) gating on the rx health stream; ESRF beam-check presets are the precedent |
| `documents(RE)` | BLISS publishes scan data to Redis — wrap the scan-data watcher as an Observable and reuse the identical HDF5/display fan-out |
| `RingHealth` Readable | a BLISS `counter` whose `read()` is the cross-system `rx.zip` |

The rx side — `ring_health`, the device pipelines, the backpressure split —
is unchanged in both mappings. That is the suite's claim in one sentence:
*the orchestrator is replaceable; the reactive composition layer is not.*
