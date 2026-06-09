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
  RxEpics/
    python/     ← migrated from RxEpics (uv/pip, RxPY v4, caproto[asyncio])
  RxTine/
    java/       ← new (jbang, RxJava3, TINE Java API)
  demo/
    synchrotron-beamline/   ← combined demo: Tango ring + EPICS beamline, 4 reactive patterns
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

- Talk planned: **"Reactive Programming in Tango"** at Tango Users Meeting
- The suite demonstrates the same reactive idioms across Tango (Java) and EPICS (Python)
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

RxTango/java produces jbang catalog artifacts; RxEpics/python produces a wheel. Independent pipelines, no shared build infrastructure needed.

## Naming conventions

GitHub org uses kebab-case (`rx-controls-suite`, `scientific-software-hub`).

