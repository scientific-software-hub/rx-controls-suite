# RxEpics — Claude Code Guide

Reactive Streams for EPICS Channel Access, Python implementation.
Stack: `caproto[asyncio]` + `reactivex` (RxPY v4), managed with `uv`.

## Project overview

Wrap EPICS Channel Access (CA) with `Observable[T]` so that ReactiveX
composition patterns — polling, zipping, sliding average, backpressure,
fluent pipelines — work on EPICS PVs with the same operator vocabulary as RxJTango.

## Setup

```bash
pip install -r requirements.txt
```

## Project layout

```
src/rxepics/
  __init__.py
  context.py            Singleton caproto async Context
  channel.py            Single-shot read → Observable
  channel_write.py      Single-shot write → Observable
  monitor.py            Push Observables: monitor_pv() (values), monitor_errors()
                         (per-update failures as messages) — share one CA subscription
  errors.py             PvUpdateError
  connection.py         connection_status() — CA connection state as Observable[bool]
  retry.py              retry_with_backoff() — for read_pv/write_pv only
  client.py             Fluent builder — EpicsClient
examples/
  read_pv.py
  poll_pv.py
  multi_pv_snapshot.py
  pv_stats.py
  pv_correlate.py
  pv_sliding_average.py
  pv_running_stats.py
  pv_throttle.py
  pv_backpressure.py
  pv_pipeline.py
  connection_status.py
  retry_pv.py
  resilient_monitor.py
tests/
  conftest.py            Fakes modeling caproto's real asyncio contract
  ioc.py                 Minimal caproto IOC for the integration test
  test_*.py              Fast by default; -m integration for the IOC test
docker-compose.yml        softIoc with test PVs
pyproject.toml
```

## Key design rules

### EpicsContext (`context.py`)
- Singleton `caproto.asyncio.client.Context` — create once, reuse everywhere
- Optional `dict[str, channel]` cache to avoid re-locating the same PV
- Cleanup via `atexit` or explicit `close()`

### Creating Observables
All sources use `rx.create(subscribe_fn)`:

```python
def subscribe(observer, scheduler):
    async def _work():
        ...
        observer.on_next(value)
        observer.on_completed()  # or on_error(exc)
    asyncio.ensure_future(_work())
return rx.create(subscribe)
```

### asyncio bridge
caproto is asyncio-native. Run the event loop explicitly in examples:

```python
loop = asyncio.get_event_loop()
scheduler = AsyncIOScheduler(loop)
source.subscribe(on_next=print, scheduler=scheduler)
loop.run_forever()
```

### Monitors are preferred
`monitor_pv()` (caproto `subscribe()`) is the primary streaming primitive.
Interval polling via `rx.interval` + `flat_map` is a fallback only.

### No commands
EPICS has no commands — `EpicsClient` has no `execute_command()`. Write to a PV instead.

### Type extraction
caproto returns numpy arrays; always take index `[0]` for scalar PVs:

```python
reading = await pv.read()
value = reading.data[0]   # numpy scalar → use float()/int()/str() as needed
```

## Test PVs

Default PV for examples: `TEST:CALC` (random ±500, 10 Hz)

| PV | Record | Role |
|---|---|---|
| `TEST:DOUBLE` | ao | static double |
| `TEST:LONG` | longout | static long |
| `TEST:STRING` | stringout | static string |
| `TEST:CALC` | calc (RNDM*1000-500, 0.1 s scan) | random generator |

Start the IOC: `docker compose up`

## Recommended implementation order

1. `context.py` — singleton context, basic locate + read
2. `channel.py` + `read_pv.py` → verify against real IOC
3. `channel_write.py` + first step of `pv_pipeline.py`
4. `monitor.py` + inline monitor example
5. Remaining examples
6. `client.py` fluent builder + full `pv_pipeline.py`

## caproto gotchas (hard-won, do not rediscover)

Verified against caproto 1.3.0. Do not assume a different version behaves the
same without re-checking the installed source.

- **The asyncio client's subscription callback is `func(sub, response)`, not
  `func(response)`.** Unlike `caproto.sync.client` and
  `caproto.threading.client`, `caproto.asyncio.client.Subscription.add_callback`
  has no back-compat signature adapter. A 1-arg callback raises `TypeError` on
  every dispatch, inside caproto's `user_callback_executor`, where it is
  silently swallowed — the monitor appears to just emit nothing.
- **caproto stores subscription and connection-state callbacks by `weakref`**
  (`CallbackHandler.add_callback`). A closure whose only strong referent is
  the chain `subscribe() -> dispose -> AutoDetachObserver` is not actually
  safe: that chain is a reference *cycle* back through the closure's own
  captured `observer`, and every example in this library discards the
  Disposable `.subscribe()` returns (they run until Ctrl+C). Once nothing
  external holds that cycle, a `gc.collect()` pass reaps it and the
  weakref-backed callback dies with it. `monitor.py` and `connection.py` pin
  the callback in a module-level `_KEEPALIVE` set until `dispose()` explicitly
  unpins it, independent of the Rx observer graph.
- **`Subscription.clear()` is a coroutine** in the asyncio client (unlike the
  sync/threading clients). Calling it without `asyncio.ensure_future`/`await`
  produces a `RuntimeWarning: coroutine ... was never awaited` and never
  actually tears down the CA subscription.
- **`pv.connection_state_callback.add_callback(f, run=True)` replays the
  current state to a late subscriber — but only if the PV has already
  connected at least once.** A PV that has never connected fires nothing.
  `connection_status()` synthesizes an initial `False` before registering, so
  the observable stays total instead of silent until first connect.
- **caproto auto-resubscribes a dropped monitor.** Verified by killing and
  restarting an IOC against one long-lived `Subscription`: disconnect is
  detected in ~1–3 s; values resume within seconds to ~15 s of the IOC
  returning (CA search retry backoff) — the subscription is re-armed
  server-side automatically, no client action needed. Do not add a reconnect
  operator for monitors; `tests/test_resilience_ioc.py` is the proof.
- **`pv.subscribe(**kwargs)` returns the same `Subscription` object for
  identical parameters** (`PV.subscriptions` keyed by the bound arg
  signature). `monitor_pv` and `monitor_errors` on the same PV therefore
  share one CA subscription — verified by checking `len(pv.subscriptions)`.
