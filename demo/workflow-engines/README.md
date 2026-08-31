# Workflow Engines — Tomography Scan via Prefect and n8n

> The same guarded scan, orchestrated by something that isn't Bluesky.
> The ladder is deliberate: **Bluesky** (easy — Python, scientific, already
> loop-based) → **Prefect** (harder — Python, no scientific assumptions) →
> **n8n** (hardest — not Python at all).

`rx-controls-suite`'s stated position is that it doesn't compete with
orchestrators, it feeds them (see `../synchrotron-beamline/bluesky/`). These
two demos stress-test that claim from progressively harder directions and
report what breaks.

```
  scan_core.py   (orchestrator-agnostic — imports guarded_scan.py unchanged)
        │  sweep_angles / sweep_frames · ScanEvent / to_events ·
        │  sustained_low · drain · ScanRun
        ├────────────────────────────┐
        ▼                            ▼
  rx_prefect.py                 refine.py          rx_n8n.py
  (5 adapters)             (QualityLedger/assess)  (3 adapters)
        ▼                            ▼                  ▼
  prefect_flow.py  ················  scan_service.py (:8030, HTTP+SSE)
  prepare → sweep ×N → finalize     POST /scan · /next · /sweep · /refine ·
     (a straight line / DAG)         /wait-healthy · /assess · /finalize · /sim/fault
                                          ▲
                                     n8n (:9000) — Form Trigger + node graph
                                     (a cycle: /assess → refine → /assess → …)
```

---

# Prefect

## Reactive patterns demonstrated

| Pattern | Where | Prefect-facing effect |
|---|---|---|
| `share()` + `sample()` backpressure | `guarded_scan.py`'s own display throttle, reused for `progress_ticks` | Protects the Artifacts API from a call per frame |
| Two-tier beam-loss gating | `wait_healthy` (tier 1, unchanged) + `sustained_low` (tier 2) | Ordinary dropouts stay invisible; a sustained one pauses the flow run visibly |
| `switch_map` cancellation | `sustained_low` | A brief flicker never starts the watchdog clock over |
| `take_until` bounding a `share()`d source | `to_events` | Per-sweep event stream that completes even though `health` runs for the whole flow |
| Cross-thread event marshalling | `scan_core.drain` (moved here from `rx_prefect.py` once `rx_n8n.py` needed it too) | The one thing worth reading first — see below |

## The thread boundary (read this before editing `rx_prefect.py`)

`RxLoop` runs every rx subscription on its own dedicated asyncio-loop thread
(rxepics/rxtango need a running loop where they subscribe). Prefect's run
context — what `get_run_logger()` and every artifact function key off — is
thread-local and does **not** cross into that thread. Worse, several Prefect
calls (`pause_flow_run`, `resume_flow_run`, the artifact creators) decide
sync-vs-async by checking for a *running event loop* as a fallback when no
run context is found — and the rx loop thread always has one running. Call
one of these from an `on_next` callback and it doesn't raise; it just returns
an unawaited coroutine and silently does nothing.

So: no Prefect SDK call may run on the rx loop thread. `scan_core.drain()` is
the fix — the rx loop thread only ever enqueues; the task's own thread
dequeues and calls every callback. The one call that can't use `drain()` is
`resume_flow_run` (it fires while the *flow's* thread is blocked inside
`pause_flow_run()`) — it hops onto a private `ThreadPoolScheduler(1)` first, a
plain worker thread with no run context and no running loop, where the same
check correctly picks the sync path. Full account in `rx_prefect.py`'s
docstring.

## Run

```bash
cd ../synchrotron-beamline && docker compose up -d --build
export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
cd ../workflow-engines && docker compose up -d           # Prefect :4200, n8n :9000
export PREFECT_API_URL=http://127.0.0.1:4200/api

python prefect_flow.py                                   # open http://127.0.0.1:4200

# second terminal — try these against a running scan
python ../synchrotron-beamline/inject_fault.py beam_loss
python ../synchrotron-beamline/inject_fault.py nominal
python ../synchrotron-beamline/inject_fault.py orbit_drift
python ../synchrotron-beamline/inject_fault.py vacuum_burst
```

| Command | What shows up in the Prefect UI |
|---|---|
| *(none)* | flow **Completed**; progress artifact reaches 100; one table artifact per sweep; markdown summary + HDF5 link |
| `beam_loss` held past `--watchdog-s`, then `nominal` | flow goes **Paused** with a reason, then **auto-resumes** — no operator click — and finishes the interrupted sweep from the right projection |
| `orbit_drift` | frames keep flowing; sweep tables show `quality: LOW`; summary's quality % drops |
| `vacuum_burst` | flow ends **Failed** with the interlock as the reason; `TOMO:SCAN:STATUS` = ABORTED; shutter closed; partial HDF5 |

---

# n8n

n8n gets a genuinely different treatment, not a re-skin of the Prefect flow.

**Why it's different.** n8n has no in-process Python step for our stack.
(n8n 2.0 didn't leave Python behind — it *replaced* the legacy Pyodide Code
node with native Python on **external task runners**. But a task-runner
sandbox is not where you run a live caproto `Context` + a rxtango event loop
against a beamline.) So the rx scan is exposed as an **HTTP+SSE service**
(`scan_service.py`) and n8n's node graph becomes the visible orchestration.

**The consequence worth publishing.** Prefect could hold the scan's live
state — `RxLoop`, the caproto `Context`, the shared `health` observable, the
open `ScanRun`, the sweep cursor — as plain Python objects passed between
`persist_result=False` tasks in one process. n8n can't: every step is a
separate HTTP call. So that state becomes a **server-side session** and n8n
is left holding only control flow. That's not a workaround; it's what
turning an experiment into a REST-addressable resource actually costs — and
buys (any HTTP client can now drive or observe it, not just this one graph).

**One simplification falls out of it.** `rx_n8n.py` is *shorter* than
`rx_prefect.py`: resuming a paused run is a plain HTTP request with no
thread-local context to respect, so the `ThreadPoolScheduler(1)` /
`async_dispatch` dance in `rx_prefect.pause_until_healthy` has no analogue
here — `resume_on_healthy` fires the resume straight from an rx `on_next`.

## It's a cycle, not a longer DAG

The Prefect flow is a straight line: `prepare → sweep ×N → finalize`. The
number of steps is known before the first frame. The n8n workflow adds a
**feedback loop** a DAG can't express — after a full pass the service assesses
which projections came out low-quality (Tango says the ring orbit was out of
spec at the moment that frame was taken) and n8n decides to re-acquire
exactly those angles, then loops. The retry list doesn't exist until the
measurement has happened.

```
  Experiment Form → POST /scan
        │
        ▼
  ┌──▶ POST /scan/{id}/next ──▶ Switch on {action}
  │        ├ sweep  → POST /sweep  ─┐
  │        ├ refine → POST /refine ─┤
  │        │                        ▼
  │        │                  IF aborted? ──true──▶ POST /finalize(aborted) → Stop And Error
  │        │                        │false
  │        │                  IF watchdog_hit? ─true─▶ POST /wait-healthy → Wait (webhook) ──┐
  │        │                        │false                                                   │
  │        ├ assess → POST /assess ─┤                                                        │
  │        └ done   → POST /finalize → End OK                                                │
  └────────────────────────────────┴────────────────────────────────────────────────────────┘
```

The service owns the cursor (`/next` returns `{action, ...}`), so sweeps and
refinement iterations collapse into one loop with one `Switch` — which also
sidesteps a documented n8n bug where `Loop Over Items` reprocesses items when
a `Wait`-on-webhook sits inside it. (This deviates from the shape the older
"n8n — next" note in this README sketched — a `Loop Over Sweeps` node — for
that reason.)

## Fault responses — five, not four

| Injected | Handled by | Visible as |
|---|---|---|
| brief beam dip | rx tier-1 gate inside `guarded_acquire_projection` | nothing — absorbed silently, as today |
| beam low > `watchdog_s` | `sustained_low` → **Wait** node | execution **Waiting**, auto-resumed when the service GETs `$execution.resumeUrl` on beam recovery; the sweep continues from the exact projection it stopped at |
| `vacuum_burst` | `interlock_trigger` → `Stop And Error` | execution ends **Error**; `TOMO:SCAN:STATUS` = ABORTED; shutter closed; partial HDF5 (unacquired rows zero-filled) |
| `orbit_drift`, then cleared | **the refinement loop** | iteration 2 re-acquires the LOW projections; quality % climbs to target; the dashboard's coverage strip turns green |
| `orbit_drift`, held | the loop's `max_iterations` guard | finishes **not converged**, reported as such — not a crash, not a silent pass |

The fourth row is the one the Prefect flow has no equivalent for, and the
reason this demo exists.

## The live-feedback gap (stated plainly)

n8n shows you one JSON blob per node execution. Prefect showed a progress
artifact updating twice a second. That is not a bug in this demo — it is what
choosing a general-purpose automation tool costs you at a beamline. The
continuous view has to come from somewhere else, so `scan_service.py` serves
its own instrument-panel dashboard at `http://127.0.0.1:8030`:

- a **coverage strip** — one tick per projection, `unacquired / OK / LOW /
  re-acquired`; you watch LOW ticks go green during iteration 2
- loop panel (iteration *k/max*, quality % vs target), machine panel
  (current, interlocks, orbit, scenario), beamline panel (angle, shutter,
  status)
- an SSE per-frame log (`GET /events`)

`../synchrotron-beamline/live_dashboard.py` (`:8000`) *also* tracks an
n8n-driven scan unchanged — it only ever read the `TOMO:SCAN:*` PVs, which
`scan_service.py` writes exactly as `guarded_scan.py` did. `scan_report.ipynb`
opens `scan_n8n_*.h5` unchanged too — same compound dtype, same `projections`
dataset.

## Run

```bash
cd ../synchrotron-beamline && docker compose up -d --build
export EPICS_CA_AUTO_ADDR_LIST=NO EPICS_CA_ADDR_LIST=127.0.0.1
cd ../workflow-engines && docker compose up -d           # Prefect :4200, n8n :9000

python scan_service.py                                   # :8030 — dashboard + API

# open http://127.0.0.1:9000
#   first launch only: create a local n8n owner account (one screen, stays on
#   this machine). Both workflows are already imported and published.
#   run "Guarded Tomography Scan" from its form; while it runs, open the
#   "Inject Fault" form in another tab and pick a scenario.
```

Suggested form values for a demo: **projections 12, sweeps 3, exposure_ms 20,
watchdog_s 6, target_quality_pct 90, max_iterations 3**.

Fault timing that matters:

- **`orbit_drift` is transient** in the simulator — the orbit rises past the
  55 µm alarm within ~3 s and decays back under it after ~17 s. Inject it
  right as pass 1 starts and keep `projections` modest so the whole pass
  lands inside that window; the frames come back LOW and the refinement loop
  has something to fix. Clear it (`nominal`) once iteration 2 begins.
- **`beam_loss`** holds until you clear it — inject it, wait for the
  dashboard to show `WAITING`, then inject `nominal` and watch it auto-resume.

`inject_fault.py` still works from a terminal if you'd rather not use the n8n
form (`python ../synchrotron-beamline/inject_fault.py beam_loss`). The n8n
"Inject Fault" workflow just POSTs `/sim/fault`, which calls the same
`rxtango.write_attribute(CONTROLLER, "ScenarioId", …)`.

## n8n container notes

- Pinned to `n8nio/n8n:2.34.1`. n8n ships a new minor most weeks; bump the
  tag in `docker-compose.yml` freely — the workflows use only core nodes
  (Form Trigger, HTTP Request, Switch, IF, Wait, Stop And Error, NoOp).
- **Host networking**, so the node graph can reach `scan_service.py` on
  `127.0.0.1:8030` and the service can reach `$execution.resumeUrl` on
  `127.0.0.1:9000`. The task-broker port is moved off its `5679` default
  (`N8N_RUNNERS_BROKER_PORT: 5691`) so a second local n8n doesn't collide.
- The entrypoint runs `import:workflow --separate` then `publish:workflow`
  per id, then `n8n start`. If `publish:workflow` churns in a newer n8n, just
  toggle each workflow **Active** once in the UI — the Form Triggers need
  that for their production URLs.
- `docker compose down -v` wipes the n8n volume (owner account, execution
  history) for a clean re-demo.

---

## Tests (no SCADA required)

```bash
uv run --with pytest pytest test_scan_core.py test_refine.py -v
```

`test_scan_core.py` covers `sweep_angles` partitioning, `to_events`'s
beam-transition-only semantics, and `sustained_low`'s flicker-immunity /
firing time — using `reactivex.testing.TestScheduler`, same convention as
`RxTango/python/tests/test_operators.py`. The one that mattered most in
practice: `to_events` must complete when its frame stream does, even though
`health` (the ring poll) never completes on its own — missing that made an
early version appear to "hang" after every frame had already arrived.

`test_refine.py` covers the `QualityLedger` (idempotent per index — a
re-acquisition overwrites a projection's verdict, it doesn't stack a second
one) and `assess`'s stop / converged / **exhausted** decision (hitting the
iteration cap with the beam still bad is reported honestly, not as a pass).

## File structure

```
scan_core.py       ★  orchestrator-agnostic: sweeps, ScanEvent stream, the
                        tier-2 watchdog, drain, the HDF5 run — no orchestrator import
refine.py          ★  the quality-driven loop: QualityLedger / assess /
                        refine_points — no orchestrator, no rx import
rx_prefect.py       ★  Prefect bridge: log_event / ProgressTracker /
                        sweep_table / pause_until_healthy (+ re-exports drain)
rx_n8n.py           ★  n8n bridge: event_json / EventHub (SSE) / resume_on_healthy
prefect_flow.py     ★  prepare_beamline → run_sweep ×N → finalize
scan_service.py     ★  FastAPI: ScanSession + the endpoints + SSE + dashboard
scan_dashboard.html ★  instrument-panel dashboard served at :8030
n8n_workflows/      ★  guarded-tomography-scan.json · inject-fault.json
test_scan_core.py      unit tests — reactivex.testing.TestScheduler
test_refine.py         unit tests — plain assertions, no scheduler
docker-compose.yml      Prefect server :4200 · n8n :9000
```
