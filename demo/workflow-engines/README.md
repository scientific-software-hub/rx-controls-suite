# Workflow Engines — Tomography Scan via Prefect

> The same guarded scan, orchestrated by something that isn't Bluesky — the
> first data point outside the "we feed scientific orchestrators" family.

`rx-controls-suite`'s stated position is that it doesn't compete with
orchestrators, it feeds them (see `../synchrotron-beamline/bluesky/`). Bluesky
is the easy case: Python, scientific, already loop-based. This demo stress-
tests the claim from two harder directions — Prefect (a general-purpose
Python orchestrator with no scientific assumptions baked in) and, next, n8n
(not Python at all).

```
  scan_core.py  (orchestrator-agnostic — imports guarded_scan.py unchanged)
        │
        ├── sweep_angles / sweep_frames   — cut one scan into N sweeps
        ├── ScanEvent / to_events          — frame | beam_ok | beam_low | interlock
        ├── sustained_low                  — tier-2 beam-loss watchdog
        └── ScanRun                        — the HDF5 file
        │
        ▼
  rx_prefect.py  (the bridge — four adapters, parallel to bluesky/rx_bluesky.py)
        │
        ▼
  prefect_flow.py
    prepare_beamline ──▶ run_sweep ×N ──▶ finalize
       (retries=2)         (retries=0)    (always runs)
```

## Reactive patterns demonstrated

| Pattern | Where | Prefect-facing effect |
|---|---|---|
| `share()` + `sample()` backpressure | `guarded_scan.py`'s own display throttle, reused here for `progress_ticks` | Protects the Artifacts API from a call per frame, not just a terminal from a print per frame |
| Two-tier beam-loss gating | `wait_healthy` (tier 1, unchanged) + `sustained_low` (tier 2, new) | Ordinary dropouts stay invisible; a sustained one pauses the flow run visibly |
| `switch_map` cancellation | `sustained_low` | A brief flicker never starts the watchdog clock over — the timer restarts clean on every drop |
| `take_until` bounding a `share()`d source | `to_events` | Per-sweep event stream that actually completes, even though `health` (the ring poll) runs for the whole flow |
| Cross-thread event marshalling | `rx_prefect.drain` | The one thing worth reading first — see below |

## The thread boundary (read this before editing `rx_prefect.py`)

`RxLoop` runs every rx subscription on its own dedicated asyncio-loop thread
(rxepics/rxtango need a running loop where they subscribe). Prefect's run
context — what `get_run_logger()` and every artifact function key off — is
thread-local and does **not** cross into that thread. Worse, several Prefect
calls (`pause_flow_run`, `resume_flow_run`, the artifact creators) decide
sync-vs-async by checking for a *running event loop* as a fallback when no
run context is found — and the rx loop thread always has one running. Call
one of these from an `on_next` callback that fires on the rx loop and it
doesn't raise; it just returns an unawaited coroutine and silently does
nothing.

So: no Prefect SDK call may run on the rx loop thread. `rx_prefect.drain()`
is the fix — the rx loop thread only ever enqueues; the task's own thread
dequeues and calls every callback, so logging, artifacts, and HDF5 writes
all happen with a valid run context. The one call that can't use `drain()`
is `resume_flow_run` (it fires while the *flow's* thread is blocked inside
`pause_flow_run()`, so there's no task thread to drain onto) — it hops onto
a private `ThreadPoolScheduler(1)` first, a plain worker thread with no
run context and no running loop, where the same sync-vs-async check
correctly picks the sync path. Full account in `rx_prefect.py`'s docstring.

## Beam loss — two tiers

**Tier 1** is already inside `guarded_acquire_projection` (unmodified):
each projection waits for a healthy beam before starting. Ordinary dropouts
are invisible to the orchestrator — just log lines.

**Tier 2** (`sustained_low`) escalates a *sustained* dropout: if beam stays
down continuously for `--watchdog-s` seconds, the current sweep task returns
early and the flow calls `pause_flow_run()` — the run shows **Paused** in
the Prefect UI with a reason. An rx subscription armed before the pause
(`pause_until_healthy`) calls `resume_flow_run` the instant beam recovers,
and the interrupted sweep picks up from the exact projection it stopped at.

An interlock (vacuum burst) aborts the run outright: the sweep task raises
`InterlockAbort`, the flow catches it just long enough to run teardown and
write the summary/link artifacts, then re-raises — the flow run ends
**Failed**, with the interlock as the reason, in the Prefect backend itself
(not just a return value an operator has to go looking for).

## Run

```bash
# Prerequisites
cd ../synchrotron-beamline && docker compose up -d --build
export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
cd ../workflow-engines && docker compose up -d          # Prefect server :4200
export PREFECT_API_URL=http://127.0.0.1:4200/api

python prefect_flow.py                                   # open http://127.0.0.1:4200

# second terminal — try these against a running scan
python ../synchrotron-beamline/inject_fault.py beam_loss
python ../synchrotron-beamline/inject_fault.py nominal
python ../synchrotron-beamline/inject_fault.py orbit_drift
python ../synchrotron-beamline/inject_fault.py vacuum_burst
```

Each fault, confirmed against the live stack:

| Command | What shows up in the Prefect UI |
|---|---|
| *(none)* | flow **Completed**; progress artifact reaches 100; one table artifact per sweep; markdown summary + HDF5 link |
| `beam_loss` held past `--watchdog-s`, then `nominal` | flow goes **Paused** with a reason, then **auto-resumes** on its own — no operator click needed — and finishes the interrupted sweep from the right projection |
| `orbit_drift` | frames keep flowing; sweep tables show `quality: LOW`; summary's quality % drops |
| `vacuum_burst` | flow ends **Failed** with the interlock as the reason; `TOMO:SCAN:STATUS` = ABORTED; shutter closed; partial HDF5 with only the acquired rows non-zero |

`../synchrotron-beamline/live_dashboard.py` (`:8000`) tracks a Prefect-driven
scan unchanged — it only ever read the `TOMO:SCAN:*` PVs, which
`scan_setup`/`scan_teardown`/`guarded_acquire_projection` still write exactly
as `guarded_scan.py` did. `scan_report.ipynb` opens `scan_prefect_*.h5`
unchanged too — same compound dtype, same `projections` dataset.

## Run the tests (no SCADA required)

```bash
uv run --with pytest pytest test_scan_core.py -v
```

Covers `sweep_angles` partitioning, `to_events`'s beam-transition-only
semantics, `sustained_low`'s flicker-immunity and firing time, and — the one
that mattered most in practice — that `to_events` actually completes when
its frame stream does, even though `health` (the ring poll) never completes
on its own. Missing that is exactly what made an early version of this demo
appear to "hang" after acquiring every frame in a sweep: every frame landed
correctly, but the task blocked forever waiting for a completion signal that
could structurally never arrive. `TestSustainedLow`/`TestToEvents` use
`reactivex.testing.TestScheduler`, same convention as
`RxTango/python/tests/test_operators.py`.

## File structure

```
scan_core.py       ★  orchestrator-agnostic: sweeps, ScanEvent stream,
                        the tier-2 watchdog, the HDF5 run — no Prefect import
rx_prefect.py       ★  the bridge: drain / log_event / ProgressTracker /
                        sweep_table / pause_until_healthy
prefect_flow.py     ★  prepare_beamline → run_sweep ×N → finalize
test_scan_core.py      unit tests against reactivex.testing.TestScheduler
docker-compose.yml      Prefect server, :4200
```

## n8n — next

n8n gets a genuinely different treatment, not a re-skin of this one: it has
no in-process Python option at all (Pyodide is a legacy feature n8n 2
dropped), so the rx scan has to be exposed as an HTTP+SSE service and n8n's
node graph becomes the visible orchestration — a `Loop Over Sweeps` node
calling `POST /scan/{id}/sweep`, an `IF` node branching on beam health, a
`Wait` node resumed by a fault-injection webhook. Expect n8n's live feedback
to be coarser than Prefect's — per-sweep node outputs, not a continuously
updating progress bar — and the README to say so plainly rather than paper
over it; that gap is itself one of the findings this pair of demos is for.
