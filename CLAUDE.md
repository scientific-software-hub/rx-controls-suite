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
    synchrotron-beamline/ ← combined demo: Tango ring + EPICS beamline, 4 reactive patterns
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

## TODO / next steps

- [x] `git mv` RxJTango → `RxTango/java/`, fix `//SOURCES` paths in jbang scripts
- [x] `git mv` RxEpics → `RxEpics/python/`, verify imports still resolve
- [x] Write root `README.md` (suite pitch + quick-start for each sub-project)
- [x] Add `CITATION.cff`
- [x] Add `LICENSE` (AGPL-3.0) + `LICENSE-COMMERCIAL.md`
- [x] Set up GitHub Actions workflows per sub-project
- [x] Add `authors` to `CITATION.cff`
- [x] Add `pyproject.toml` to `RxEpics/python/` (needed for wheel build in CI)
- [x] Implement missing `RxEpics/python/src/rxepics/context.py` and `client.py`
- [x] Add `RxTango/python` — reactive Tango wrapper (PyTango + RxPY v4, mocked tests)
- [x] Add `demo/synchrotron-beamline/` — combined storage ring + beamline demo (4 reactive patterns)
- [x] Add `docs/combined-demo-talk/` — capstone HTML deck + slides.md
