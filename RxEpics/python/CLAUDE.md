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
  monitor.py            Push Observable wrapping caproto subscribe
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
