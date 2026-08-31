# rx-controls-suite — Claude Code Guide

## What this is

A monorepo suite of reactive programming wrappers for scientific control system frameworks, living under the `scientific-software-hub` GitHub org.

**Elevator pitch:** Same ReactiveX operator vocabulary (poll, zip, sliding average, backpressure, fluent pipelines) across multiple control system platforms.

## Repo structure

```
rx-controls-suite/
  RxTango/
    java/       ← migrated from RxJTango (jbang, RxJava3, ezTangoAPI)
    python/     ← new (uv, RxPY v4, PyTango; unit-tested with mocked DeviceProxy)
    cpp/        ← new (CMake + FetchContent, RxCpp, cppTango; header-only)
  RxEpics/
    python/     ← migrated from RxEpics (uv/pip, RxPY v4, caproto[asyncio])
    cpp/        ← new (CMake + FetchContent, RxCpp, PVXS; header-only)
  RxTine/
    java/       ← new (jbang, RxJava3, TINE Java API)
  RxDectris/
    python/     ← new (uv, RxPY v4, httpx + pyzmq/CBOR; wraps DECTRIS SIMPLON — detector, not facility)
  demo/
    synchrotron-beamline/   ← combined demo: Tango ring + EPICS beamline, 4 reactive patterns
      bluesky/              ← same scan under a Bluesky RunEngine; rx↔Bluesky bridge (RxStatus/RxSignal/rx_wait/documents)
    reactive-query-cache/   ← app-level Rx cache demo: QueryCache dedup across UI components
    dectris-integration/    ← simulated DECTRIS detector + D.LAB mock, gated by either facility adapter
  (RxEpics/java, RxTine/python — future)
```

## Sub-project summaries

### RxTango/java (origin: RxJTango)

Wraps [ezTangoAPI](https://github.com/hzg-wpi/ez-tango-api) (`TangoProxy`) with reactive-streams `Publisher` interfaces.

**Build:** [jbang](https://www.jbang.dev/) — no Maven build step. Each script in `examples/` is self-contained with inline `//DEPS`. Tango artifacts (`ezTangoAPI`, `TangORB`) must be pre-installed in `~/.m2` (not on Maven Central).

**Class hierarchy (`src/`, package `org.tango.client.rx`):**
- `RxTango<T>` — abstract base `Publisher<T>`; single-shot (one item per subscription)
  - `RxTangoCommand<T,V>` — executes a Tango command
  - `RxTangoAttribute<T>` — reads an attribute
  - `RxTangoAttributeWrite<T>` — writes an attribute, emits `Void`
- `RxTangoAttributeChangePublisher<T>` — push/multi-value publisher backed by Tango events (`CHANGE`, `PERIODIC`, `ARCHIVE`)

**Key design:** Single-shot publishers; use `Flowable.interval(...).flatMapSingle(...)` for polling. Production code depends only on `org.reactivestreams`; RxJava3 used in examples only.

### RxTine/java

Wraps [TINE](https://tine.desy.de) (Three-fold Integrated Networking Environment,
DESY) with reactive-streams `Publisher` interfaces via the TINE Java client API.

**Build:** jbang — no Maven. TINE jar must be manually installed in `~/.m2`
(not on Maven Central).

**Class hierarchy (`src/`, package `org.tine.client.rx`):**
- `RxTine<T>` — abstract base `Publisher<T>`; single-shot (one item per subscription)
  - `RxTineRead<T>` — reads a property via `TLink.executeAndClose()`
  - `RxTineWrite<T>` — writes a property, emits written value
- `RxTineMonitor<T>` — push/multi-value publisher backed by `TLink.attach(CM_POLL)`
- `TineClient` — fluent builder mirroring TangoClient (no executeCommand — TINE
  has no commands)

**Key design:** same single-shot + push separation as RxTango. Address is a
`devName` + `property` pair (e.g. `/HERA/Context/Device`, `SENSOR`).
`TDataType` always returns arrays; take index `[0]` for scalars.

### RxEpics/python (origin: RxEpics)

Wraps EPICS Channel Access with `Observable[T]` via `caproto[asyncio]` + `reactivex` (RxPY v4), managed with `uv`.

**Layout (`src/rxepics/`):** `context.py` (singleton caproto Context), `channel.py` (single-shot read), `channel_write.py` (single-shot write), `monitor.py` (push Observable), `client.py` (fluent `EpicsClient` builder).

**Key design:** `monitor_pv()` is the primary streaming primitive. No commands (EPICS has none — write to a PV instead). caproto returns numpy arrays; always take index `[0]` for scalars.

### RxTango/cpp

Wraps [cppTango](https://github.com/tango-controls/cppTango) (`Tango::DeviceProxy`) with `rxcpp::observable<T>` streams.

**Build:** CMake 3.18+ with `FetchContent` for RxCpp; cppTango found via `pkg_check_modules(TANGO REQUIRED IMPORTED_TARGET tango)`. Header-only library — no compiled artifact. Run `cmake -S . -B build && cmake --build build`.

**Function hierarchy (`include/rxtango/`, namespace `rxtango`):**
- `read_attribute<T>(device, name)` → `observable<T>` — single-shot; `std::thread` + `DeviceProxy::read_attribute()`
- `write_attribute<T>(device, name, value)` → `observable<T>` — re-emits written value
- `execute_command<R,A>(device, cmd, argin=nullopt)` → `observable<R>` — optional argin
- `monitor_attribute<T>(device, name, event)` → `observable<T>` — push; `detail::EventCallback<T>` inherits `Tango::CallBack`; dispose calls `unsubscribe_event()`
- `TangoContext` — Meyers singleton caching `DeviceProxy` per device string; `std::mutex` protected
- `TangoClient` — fluent builder over `observable<std::any>`; `read`, `monitor`, `write`, `execute`, `map`, `subscribe`

**Key design:** Same single-shot + push split as Java/Python. `std::thread::detach()` dispatches blocking cppTango calls. `detail::EventCallback<T>` uses `std::mutex` to serialise cppTango's event callback thread. Conformance test (`tests/verify_contract.cpp`) verifies C1–C6 ReactiveX contract rules against live TangoTest.

### RxEpics/cpp

Wraps [PVXS](https://github.com/mdavidsaver/pvxs) (`pvxs::client::Context`) with `rxcpp::observable<T>` streams.

**Build:** CMake 3.18+ with `FetchContent` for RxCpp; PVXS found via `find_package(PVXS)` with pkg-config fallback. Header-only library. Requires `EPICS_PVA_ADDR_LIST` env var.

**Function hierarchy (`include/rxepics/`, namespace `rxepics`):**
- `read_pv<T>(name, ctx)` → `observable<T>` — single-shot; `ctx.get(name).exec()->wait(5.0)` on detached thread; extracts `val["value"].as<T>()`
- `write_pv<T>(name, value, ctx)` → `observable<T>` — re-emits written value
- `monitor_pv<T>(name, ctx)` → `observable<T>` — push; `pvxs::client::Monitor` kept alive via `shared_ptr`; dispose destroys handle → subscription cancelled
- `EpicsContext` — Meyers singleton wrapping `pvxs::client::Context::fromEnv()`; `default_context()` free function
- `EpicsClient` — fluent builder (no `execute` — EPICS has no commands)

**Key design:** No commands — write to a command PV instead. PVXS Monitor lifetime managed via `shared_ptr` in cleanup lambda. First EPICS subproject in the suite with a reactive conformance test.

### RxDectris/python

Wraps a DECTRIS **SIMPLON** detector (REST config/status/command + a real Stream V2
ZeroMQ/CBOR socket) with `Observable[T]` via RxPY v4, managed with `uv`. Unlike every
other sub-project, the platform on the other end is a **detector**, not a facility
control system — this is the seam a facility-orchestration demo (`demo/dectris-integration/`)
plugs into.

**Layout (`src/rxdectris/`):** `context.py` (`DetectorContext`, one httpx client + one
zmq PULL socket per DCU base URL), `config.py`/`status.py`/`command.py` (single-shot REST
primitives — `read_config`, `write_config`, `read_status`, `send_command` +
`initialize`/`arm`/`trigger`/`disarm`/`abort`/`cancel`), `stream.py` (`stream2` — push
Observable of `SeriesStart`/`Frame`/`SeriesEnd`, `configure_stream`), `monitor.py`
(`monitor_images` — the HTTP Monitor subsystem, `mode="next"` vs `mode="monitor"`),
`client.py` (`DectrisClient` fluent builder), `recipes.py` (`acquire_series` — the
lifecycle recipe: configure → enable stream → subscribe *before* arm → arm → trigger →
frames until `SeriesEnd` → disarm, with unconditional abort-on-error/-disposal teardown).

**Key design:** Stream V2's `start` is emitted by `arm`, not `trigger` — `acquire_series`
subscribes to the socket before arming for exactly this reason. Config writes can cascade
(`count_time` forcing `frame_time` up) and the wrapper surfaces SIMPLON's own "changed
parameters" response rather than hiding it. `abort` (immediate) and `cancel` (finishes the
image in flight) are distinct verbs, not aliases. See
[`RxDectris/python/README.md`](RxDectris/python/README.md)'s "what is simulated / what
is not" table — the demo's `simplon_sim` is built against the public *SIMPLON 1.8 API
documentation* only, and the D.LAB mock (`demo/dectris-integration/dlab_sim/`) is
explicitly conceptual since no public D.LAB endpoint spec exists.

### demo/synchrotron-beamline/bluesky

The guarded tomography scan re-orchestrated by a **Bluesky RunEngine**, positioning
the suite as Bluesky's cross-control-system composition layer (Bluesky/ophyd is
EPICS-native; the Tango ring is invisible to it without rx).

**Files:**
- `rx_bluesky.py` — the whole bridge in four adapters: `RxLoop` (dedicated asyncio
  loop thread for rx subscriptions — rxepics/rxtango require a running loop),
  `RxStatus` (Observable → Bluesky Status), `RxSignal` (Observable → ophyd-Signal
  shim for suspenders), `rx_wait` (Observable → blocking read), `documents`
  (RunEngine → Observable of `(name, doc)`)
- `devices.py` — Bluesky-protocol devices (Readable/Movable/Triggerable) implemented
  directly on rxepics/rxtango pipelines; no ophyd, no pyepics. `RingHealth` puts
  Tango state + derived `quality_ok` into every Event document
- `guarded_scan_bluesky.py` — `bp.scan` with beam-loss handled by
  `SuspendBoolLow(RxSignal(beam_ok))`, interlock abort via `RE.request_pause()` →
  `RE.abort()`, and the document stream fanned back into rx (HDF5 raw / display sampled)

**Key design:** two event loops (RunEngine's + `RxLoop`'s) bridged exclusively with
`call_soon_threadsafe`; suspender callbacks fan out on a worker thread so the rx loop
stays free for device reads. Scan-state PVs are mirrored from documents, so
`live_dashboard.py` tracks Bluesky scans unchanged. BLISS mapping documented as a
design sketch in `bluesky/README.md` (BLISS needs its Beacon+Redis stack — not
reducible to this docker demo).

**Known gotchas (hard-won, do not rediscover):**
- **caproto + uvloop = silent CA search failure.** Under `uvicorn[standard]`,
  uvloop becomes the default loop and caproto's UDP name search never resolves —
  every PV hangs in `(searching....)` until a `CaprotoTimeoutError`, with correct
  `EPICS_CA_*` env. TCP is unaffected, so it looks like a network problem. Fix:
  `uvicorn.run(..., loop="asyncio")` (see `bluesky/live_strip.py`).
- **Tango "Device not exported" after a docker stack restart.** If the Tango DB
  containers restart while `storage-ring-sim-server` keeps running, *new* clients
  fail with `API_DeviceNotExported` while processes holding cached `DeviceProxy`
  connections keep reading happily — the contradiction is the tell. Fix:
  `docker restart storage-ring-sim-server` so it re-registers with the DB.

### demo/workflow-engines

The guarded tomography scan orchestrated by **Prefect** and by **n8n**, instead
of a hand-rolled script or Bluesky's `RunEngine` — data points outside the
"scientific orchestrator" family, stress-testing the suite's "we feed
orchestrators, we don't replace them" claim. Prefect is the general-purpose-
Python angle; n8n is the not-Python-at-all angle: the rx scan is exposed as an
HTTP+SSE service (`scan_service.py`, `:8030`) and n8n's node graph is the
orchestration. Two findings the n8n half exists to show: (1) with no in-process
Python step, the scan's live state has to become a **server-side session** and
the orchestrator holds only control flow — that's the cost/benefit of making an
experiment a REST resource; (2) the n8n graph is a genuine **cycle**, not a
longer DAG — a quality-driven refinement loop (`refine.py`) re-acquires the
projections a full pass flagged LOW and re-assesses, which a DAG can't express.
n8n 2.0 replaced Pyodide with native Python on external task runners (not "no
Python at all" — but not a beamline-appropriate place for a live caproto
Context either).

**Files:**
- `scan_core.py` — orchestrator-agnostic: reuses `guarded_acquire_projection`
  from `synchrotron-beamline/guarded_scan.py` unmodified; adds `sweep_angles`/
  `sweep_frames` (cut one scan into N sweeps; `sweep_frames` takes an optional
  explicit `indices` list for non-contiguous refinement passes), `ScanEvent`/
  `to_events`, `sustained_low` (tier-2 beam-loss watchdog), `drain` (rx loop
  thread → calling thread boundary, shared by both bridges), `ScanRun` (HDF5;
  per-index quality dict so a re-acquisition overwrites, not double-counts). No
  orchestrator import.
- `refine.py` — the quality-driven loop, no orchestrator/rx import:
  `QualityLedger` (last-known quality per projection index, idempotent),
  `assess` (stop / converged / *exhausted* decision), `refine_points`
  (LOW indices → `(index, angle)` pairs).
- `rx_prefect.py` — Prefect bridge: `log_event`, `ProgressTracker`,
  `sweep_table`, `pause_until_healthy` (→ `resume_flow_run`); re-exports `drain`.
- `rx_n8n.py` — n8n bridge, three adapters: `event_json`, `EventHub` (fan-out to
  SSE clients), `resume_on_healthy` (GET `$execution.resumeUrl` on beam
  recovery — no `ThreadPoolScheduler` hop needed, unlike Prefect's).
- `prefect_flow.py` — `prepare_beamline → run_sweep ×N → finalize`.
- `scan_service.py` — FastAPI: `ScanSession` + `/scan` `/next` `/sweep`
  `/refine` `/wait-healthy` `/assess` `/finalize` `/sim/fault` + SSE `/events`
  + the dashboard. `/sweep` and `/refine` are sync `def` so they can block in
  `drain`. `uvicorn.run(..., loop="asyncio")` for the caproto+uvloop gotcha.
- `scan_dashboard.html` — instrument-panel dashboard at `:8030`; coverage strip
  (unacquired / OK / LOW / re-acquired) is the centerpiece.
- `n8n_workflows/` — `guarded-tomography-scan.json` (Form Trigger → the `/next`
  cursor loop) + `inject-fault.json` (dropdown → `/sim/fault`); imported +
  published by the n8n container's entrypoint.

**Key design:** two-tier beam loss — the existing per-projection `wait_healthy`
gate absorbs ordinary dropouts invisibly; `sustained_low` escalates a *sustained*
one to `pause_flow_run()` (not `suspend_flow_run` — suspend tears the process
down, killing the open HDF5 handle and the rx loop thread), with an rx
subscription armed before the pause auto-calling `resume_flow_run` the instant
beam recovers. A vacuum-burst interlock re-raises after teardown so the flow run
itself ends **Failed** with the reason, not just a buried return value.

**Known gotchas (hard-won, do not rediscover):**
- **Prefect's run context is thread-local; the rx loop thread doesn't have one.**
  `get_run_logger()` and every artifact function key off
  `prefect.context.get_run_context()`, which only exists on the thread that
  entered the task/flow. rx subscriptions all run on `RxLoop`'s dedicated
  background thread (rxepics/rxtango need a running loop where they subscribe).
  Calling a Prefect SDK function from an `on_next` callback that fires on the rx
  loop either raises `MissingContextError` or — worse — silently no-ops (see
  next gotcha). Fix: `rx_prefect.drain()` only ever enqueues on the rx loop
  thread; the task's own thread dequeues and invokes every callback, so all
  Prefect calls happen with a valid run context.
- **`async_dispatch`'s loop-detection trap.** `pause_flow_run`, `resume_flow_run`,
  and the artifact creators are wrapped in `@async_dispatch`, which — on
  `MissingContextError` — falls back to `asyncio.get_running_loop()` to decide
  sync vs. async. The rx loop thread always has one running (that's how
  `AsyncIOThreadSafeScheduler` dispatches), so the check wrongly concludes
  "async context" and returns an **unawaited coroutine**: nothing raises, the
  call is just a no-op. `resume_flow_run` can't go through `drain()` either — it
  fires while the *flow's* thread is blocked inside `pause_flow_run()`. Fix:
  `pause_until_healthy` hops onto a private `ThreadPoolScheduler(1)` first — a
  plain worker thread with no run context and no running loop — where the same
  check correctly picks the sync path.
- **A `share()`d source's downstream must complete on its own lifetime, not its
  perpetual upstream's.** `to_events` merges per-sweep `frames` with
  beam/interlock branches derived from `health` (the ring poll, shared and
  running for the whole flow, never completing). A bare `rx.merge` never
  completes either, since `rx.merge` needs *every* source to — so anything
  blocking on `on_completed` (`drain`) hangs forever *after* every frame in the
  sweep has already arrived, which reads exactly like a mid-scan freeze and
  isn't one. Fix: `to_events` applies `take_until(_completion_of(frames))`, safe
  because a `Subject`-backed `share()` delivers a value to every observer before
  it delivers the completion that follows it — no data loss.
- **No `prefect/` subdirectory.** `prefect_flow.py` puts its own parent on
  `sys.path` to import `scan_core`; a sibling directory literally named
  `prefect/` would shadow the real `prefect` package as an implicit namespace
  package. Layout stays flat for exactly this reason.
- **n8n's Wait node resumes on GET, not POST.** `resume: webhook` registers its
  restart hook as `$parameter["httpMethod"] || "GET"` — `resume_on_healthy`
  must GET `$execution.resumeUrl`. A POST 404s with "does not contain a waiting
  webhook with a matching path/method" and the run stays parked forever.
- **n8n Form Trigger submissions are `multipart/form-data`** keyed `field-0`,
  `field-1`, … (the HTML input names), not the field labels. The label is only
  the *output* key (`$json.<label>` for typeVersion < 2.4). Matters only if you
  script the form with curl — the browser does the right thing.
- **n8n's internal task-broker port (5679) is fixed per instance**; with host
  networking two local n8n instances collide and the second exits(1) right
  after "n8n ready". `docker-compose.yml` moves ours to 5691.

**Run:** `docker compose up -d` (Prefect `:4200` + n8n `:9000`) alongside the
synchrotron-beamline stack. Prefect: `python prefect_flow.py`. n8n:
`python scan_service.py` then drive it from `http://127.0.0.1:9000` (both
workflows arrive imported + published).

**Companion talk:** `docs/prefect-talk/` — a manager/beamline-scientist-facing slide
deck (screenshots of both scenarios in the Prefect UI, no code), separate from
`prefect-walkthrough.html`'s engineering deep-dive above.

### demo/reactive-query-cache

Demonstrates an **app-level cache** built from the suite's own Rx primitives — conceptually a TanStack-Query `QueryClient`, implemented with `ReplaySubject` + ref-count + a gc grace timer.

**The problem it solves:** the suite's primitives (`read_attribute`, `read_pv`) are cold/unicast — every `.subscribe()` opens its own upstream SCADA read. In a multi-component UI, N panels requesting the same key = N upstream reads. The `QueryCache` coalesces all requests for the same key into **one** upstream subscription, keeping SCADA load constant as component count grows.

**Files:**
- `query_cache.py` — `QueryCache` class: dedup, `replay(1)` last-value cache, `stale_ms`, `gc_ms` teardown
- `querycache_dashboard.py` — FastAPI backend: per-component SSE `/subscribe`, `/metrics/stream` inspector feed
- `index.html` — vanilla-JS shell: Ring SVG component + Table component + Cache-Inspector panel + spawn/kill controls
- `test_query_cache.py` — 7 unit tests against a synthetic upstream (no SCADA needed)

**Transport note:** one `EventSource` per component hits the browser HTTP/1.1 ~6-connection limit at ~5 components. For more, replace with a single multiplexed WebSocket `/ws`; `QueryCache` is unchanged.

**Run:** `uv run --with fastapi --with "uvicorn[standard]" python querycache_dashboard.py` (requires the synchrotron-beamline docker stack).

### demo/dectris-integration

Built for a specific commercial meeting (DECTRIS Ltd.): puts a simulated **DECTRIS
detector** into the synchrotron-beamline story so a detector-vendor audience doesn't have
to mentally translate a Tango/EPICS-only demo onto their own products. The reveal is the
same one `demo/synchrotron-beamline` already makes, in DECTRIS's vocabulary: swap
`--facility tango` for `--facility epics` and the experiment recipe is unchanged.

**Files:**
- `simplon_sim/` — FastAPI SIMPLON simulator: `state.py` (the state machine — `na → idle →
  ready → acquire → idle`, config cascades, `abort` vs `cancel`, fault injection) + `app.py`
  (routes + the real Stream V2 ZeroMQ PUSH/CBOR socket on `:31001`)
- `dlab_sim/` — a conceptual D.LAB-shaped mock (Projects/Datasets/Jobs); **not** a
  reproduction of the real D.LAB API — none is public
- `facilities.py` — `FacilityHealth`, the `Facility` protocol, `TangoFacility` (wraps
  `demo/synchrotron-beamline/facility.py::ring_health` unmodified), `EpicsFacility` (reads
  the `FAC:*` PV mirror), `FakeFacility` (scripted, for adapter-invariance tests). Named
  `facilities.py`, plural — `facility.py` was already taken by the sibling demo's module,
  and both land on `sys.path` simultaneously
- `facility_bridge.py` — mirrors the Tango ring into 4 new `FAC:*` records added to
  `RxEpics/python/demo/tomography/tomography.db` (additive), so `EpicsFacility` sees the
  same simulated machine `TangoFacility` sees, with no EPICS gateway
- `recipes.py` — `wait_until_healthy`, `guarded_by`/`abort_on`, `correlate_with` (per-frame
  facility stamping → `AcquiredFrame`), `process_with`/`validate_result` (D.LAB stage, with
  retry), `AcquisitionRun` (HDF5 sink — same indexed-write idiom as
  `demo/workflow-engines/scan_core.py`'s `ScanRun`, different compound dtype so not the
  same class)
- `experiment.py` — the hero pipeline, `--facility epics|tango`
- `inject_fault.py` — one command for all four fault families (ring scenarios reuse
  `rxtango.write_attribute` exactly like the sibling demo's script; detector/D.LAB faults
  are `/_sim/fault` PUTs)
- `dashboard.py` + `index.html` — FACILITY/DETECTOR/D.LAB status, polls all three services
  directly (no coupling to `experiment.py`'s process), `:8020`, neon palette matching
  `demo/synchrotron-beamline/dashboard.html`

**Key design / gotchas (hard-won, do not rediscover):**
- **Stream V2's `start` fires on `arm`, `end` fires on the internal-trigger-mode
  auto-disarm** (SIMPLON 1.8 API documentation, not a simplification) — `RxDectris`'s
  `acquire_series` recipe already handles this; `simplon_sim/state.py` reproduces it
  faithfully so the demo and the real product agree.
- **A PUSH socket round-robins across every peer that ever connected, including ones that
  vanished without a clean disconnect.** Every short-lived demo script here opens a fresh
  ZeroMQ connection per process; without `SNDTIMEO` on the PUSH socket, one dead peer's full
  queue can block `emit()` — and therefore every command handler that calls it — hanging the
  whole simulated detector, not just the stream. Fixed with a 1s `SNDTIMEO` + drop-not-hang
  in `simplon_sim/app.py`'s lifespan. Running two client processes against the simulator in
  rapid succession (as opposed to one at a time, as the real demo does) can still show
  cross-talk between their streams — an inherent property of PUSH/PULL round-robin, not a
  recipe bug.
- **`correlate_with` uses `concat_map`, not `flat_map`.** `facility.snapshot()` is an async
  per-frame read; `flat_map` does not preserve arrival order when inner observables settle
  out of order, so `SeriesEnd` (`rx.of`, instant) would print before a still-pending frame's
  correlation. `_CachingFacility` (in `facilities.py`) makes this free: `snapshot()` returns
  a cached last-value read, not a fresh poll, so serializing via `concat_map` costs no real
  latency per frame.
- **`abort_on`'s abort must be inside the `take_until` trigger, not a `do_action` beside
  it.** A fire-and-forget `abort(ctx).subscribe(...)` next to the cutoff races the rest of
  the pipeline completing and the caller closing its `DetectorContext` right after — the
  abort HTTP request can be dropped before it's ever sent, leaving the real detector stuck
  mid-series. Fix: `trigger.pipe(flat_map(lambda t: abort(ctx).pipe(map(lambda _: t))))` as
  the `take_until` argument, so the cutoff only fires once abort has actually completed.
- **A D.LAB job that settles with `status: "failed"` is a value, not an rx error.**
  `retry_with_backoff` only catches exceptions, so `process_with` has to raise on a failed
  job status itself, *before* the retry wrapper — not after, via a separately-composed
  `validate_result()` — or nothing ever retries.
- **`initialize()` must not clear an injected fault.** Every normal `acquire_series` run
  calls `initialize()` unconditionally at startup (to recover from a fresh "na" DCU); if
  that also cleared `_fault_pending`, a fault injected before a run would never be observed.
  Only an explicit `/_sim/fault {"value":"nominal"}` (or `abort`'s own error-state recovery
  branch) clears it.

**Run:** `docker compose up -d --build` (includes `demo/synchrotron-beamline`'s stack, plus
`simplon-sim`/`dlab-sim`), `uv pip install -e RxDectris/python`, then
`python experiment.py --facility tango --frames 100 --count-time 0.01`. See
[`demo/dectris-integration/README.md`](demo/dectris-integration/README.md) for the full run
book and [`demo-script.md`](demo/dectris-integration/demo-script.md) for the meeting sequence.

## Context & motivation

- Talks planned at Tango Users Meeting (Java, Python, C++) and EPICS Collaboration Meeting (Python, C++)
- The suite demonstrates the same reactive idioms across Tango (Java, Python, C++), EPICS (Python, C++), and TINE (Java)
- Future: additional platforms (OPC-UA, DOOCS), additional languages

## License decision

**AGPL-3.0** for open/non-commercial use + commercial license negotiation for vendors.

- AGPL forces anyone shipping a product or running a SaaS with modified code to publish their source — creating natural pressure to negotiate a commercial license instead
- Non-commercial / research use is free
- Citation handled via `CITATION.cff` (to be created), integrates with Zenodo and GitHub's "Cite this repository"

## GitHub Actions strategy

Path-filtered workflows — each sub-project has its own workflow, triggered only on changes to its subtree:

```yaml
on:
  push:
    paths: RxTango/java/**
```

RxTango/java produces jbang catalog artifacts; RxEpics/python produces a wheel; the C++ subprojects run CMake structure-validation (no cppTango/PVXS needed in CI). Independent pipelines, no shared build infrastructure needed.

## Naming conventions

GitHub org uses kebab-case (`rx-controls-suite`, `scientific-software-hub`).

