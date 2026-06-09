# Reactive Query Cache

> **Concept:** how an Rx-backed app-level cache keeps upstream SCADA load
> constant as the number of UI components grows.

## The problem

Every call to a cold Observable — `read_attribute(...)`, `read_pv(...)` — opens
its own upstream network read.  In a multi-component frontend, many panels
requesting the same data key means duplicated SCADA traffic that scales linearly
with component count:

```
component A  subscribed to ring.current ──► Tango read #1 (every 1 s)
component B  subscribed to ring.current ──► Tango read #2 (every 1 s)
component C  subscribed to ring.current ──► Tango read #3 (every 1 s)
                                           ──────────────────────────
                                           3 upstream reads for 1 value
```

## The solution: QueryCache

`query_cache.py` implements a `QueryCache` built entirely from the suite's own
Rx primitives.  It sits between the primitives and the UI:

```
component A ──┐
component B ──┤── /subscribe (SSE) ──► QueryCache ──► 1 upstream sub for ring.current
component C ──┘                        ReplaySubject   (rx.interval + flat_map)
                                        replay(1)
                                        ref-count + gc
```

No matter how many components subscribe to the same key, the cache maintains
**exactly one** upstream subscription per unique key.

## Architecture

```
Browser                             Python backend
──────────────────────────────────  ──────────────────────────────────────
Ring component A   EventSource  ──► GET /subscribe?keys=ring.current,…
                                        │
Table component B  EventSource  ──► GET /subscribe?keys=ring.current,…
                                        │
                                   QueryCache.observe("ring.current")
                                     ┌─────────────────────────┐
                                     │  ReplaySubject(1)        │◄── upstream sub
                                     │  (shared multicast bus)  │    (ONE per key)
                                     └─────────────────────────┘
                                              │
                                   rx.interval(1s).flat_map(read_attribute)
                                              │
                                        Tango / EPICS
```

Inspector panel (right sidebar) streams `GET /metrics/stream` (SSE at 2 Hz) and
shows the live headline:

    14 component subs  →  8 SCADA subs    (ops/sec stays flat)

## QueryCache features

| Feature | Rx primitive | Effect |
|---------|-------------|--------|
| **Dedup** | single `source.subscribe()` per key | N panels → 1 upstream sub |
| **Last-value cache** | `ReplaySubject(buffer_size=1)` | late subscriber gets cached value immediately |
| **stale_ms** | timestamp of last value vs. `stale_ms` | value tagged fresh/stale in inspector |
| **gcTime** | `loop.call_later(gc_ms, ...)` | upstream stays warm for `gc_ms` after last observer leaves |
| **GC cancel** | cancel handle on new subscriber | re-subscribing inside grace window reuses warm upstream |
| **Auto-reconnect** | `on_error` retry after 2 s | transient SCADA errors don't break the cache |

## Query keys

| Key | Source | Type |
|-----|--------|------|
| `ring.current` | Tango `sr/demo/controller` BeamCurrent | float mA |
| `ring.interlocks` | Tango InterlockCount | int |
| `ring.lifetime` | Tango LifetimeHours | float h |
| `ring.scenario_id` | Tango ScenarioId | int |
| `sector04.orbit_x` | Tango `sr/demo/sector04` OrbitX | float µm |
| `sector04.vacuum` | Tango VacuumPressure | float mbar |
| `sector04.radiation` | Tango RadiationDoseRate | float mGy/h |
| `beam.angle` | EPICS `TOMO:ROT:VAL` | float ° |
| `beam.shutter` | EPICS `TOMO:SHUTTER:OPEN` | int 0/1 |
| `beam.counts` | EPICS `TOMO:DET:COUNTS` | int |

## Run

### Prerequisites

```bash
# 1. Start the Tango ring + EPICS beamline (shared with the sibling demo)
docker compose -f ../synchrotron-beamline/docker-compose.yml up -d --build

# 2. Set EPICS channel access env (every shell that runs the backend)
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1
```

### Start the backend

```bash
# from demo/reactive-query-cache/
uv run --with fastapi --with "uvicorn[standard]" python querycache_dashboard.py
```

Open <http://127.0.0.1:8000>.

### Observe the dedup

1. **Initial state:** one Ring component + one Table component.
   Inspector shows `ring.current` has **2 observers**, **1 upstream sub**.

2. **Spawn more components:** click `+ Ring component` several times.
   Watch **component subs** climb in the inspector while
   **upstream SCADA subs** stays flat.  `ops/sec` stays constant.

3. **Kill components:** click `Kill last Ring` repeatedly.
   When the last consumer of a key leaves, the `⏱` GC badge appears —
   the upstream stays warm for 10 s (gc_ms), then the `●` turns `○`.

4. **Re-mount within gc window:** click `+ Ring component` before the GC
   fires.  The upstream reconnects instantly with the *cached* last value
   (no wait for the next poll tick) — that's `replay(1)` in action.

### Run the unit tests (no SCADA required)

```bash
uv run --with pytest pytest test_query_cache.py -v
```

Tests cover: dedup, last-value cache, gc teardown, gc-cancel on re-subscribe,
and metrics accuracy — all against a synthetic upstream with no network calls.

## File structure

```
demo/reactive-query-cache/
  query_cache.py          ← THE STAR: Rx-based QueryCache (dedup + replay + gc)
  querycache_dashboard.py ← FastAPI backend: SSE /subscribe + /metrics/stream
  index.html              ← vanilla-JS multi-component shell (no build step)
  test_query_cache.py     ← unit tests for cache semantics (synthetic source)
  README.md               ← this file
```

## Relation to the sibling demo

`demo/synchrotron-beamline/` shows reactive patterns *inside* a single pipeline
(polling, zipping, guarding, backpressure).

This demo shows what happens *above* those pipelines when multiple independent
UI consumers request overlapping data — and how an Rx-built cache layer
coalesces that demand without any external data-fetching library.

## Note on push vs. poll

`QueryCache` uses polled sources (`rx.interval` + `flat_map`) to keep the
upstream ops/sec metric transparent.  The same architecture works equally well
with push sources (`monitor_attribute`, `monitor_pv`) — just replace the
`rx.interval`-based factory with a `monitor_*` observable.  The `ReplaySubject`
multicast + ref-count + gc logic is unchanged.
