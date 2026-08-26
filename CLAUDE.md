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
  demo/
    synchrotron-beamline/   ← combined demo: Tango ring + EPICS beamline, 4 reactive patterns
      bluesky/              ← same scan under a Bluesky RunEngine; rx↔Bluesky bridge (RxStatus/RxSignal/rx_wait/documents)
    reactive-query-cache/   ← app-level Rx cache demo: QueryCache dedup across UI components
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

The guarded tomography scan orchestrated by **Prefect** instead of a hand-rolled
script or Bluesky's `RunEngine` — the first data point outside the "scientific
orchestrator" family, stress-testing the suite's "we feed orchestrators, we don't
replace them" claim from a general-purpose-Python angle. An n8n variant (no
in-process Python option at all — Pyodide is legacy, n8n 2 dropped it) is next;
its design (n8n owns the sweep loop via HTTP+SSE against a `scan_core.py`-backed
service) is recorded in `workflow-engines/README.md`'s closing section.

**Files:**
- `scan_core.py` — orchestrator-agnostic: reuses `guarded_acquire_projection`
  from `synchrotron-beamline/guarded_scan.py` unmodified; adds `sweep_angles`/
  `sweep_frames` (cut one scan into N sweeps), `ScanEvent`/`to_events` (a flat
  frame/beam_ok/beam_low/interlock stream), `sustained_low` (tier-2 beam-loss
  watchdog), `ScanRun` (the HDF5 file). No Prefect import.
- `rx_prefect.py` — the bridge, four adapters parallel to `bluesky/rx_bluesky.py`'s:
  `drain` (rx loop thread → task thread boundary), `log_event`, `ProgressTracker`,
  `sweep_table`, `pause_until_healthy` (→ `resume_flow_run`)
- `prefect_flow.py` — `prepare_beamline → run_sweep ×N → finalize`

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

**Run:** `docker compose up -d` (Prefect server, `:4200`) alongside the
synchrotron-beamline stack, then `python prefect_flow.py`.

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

