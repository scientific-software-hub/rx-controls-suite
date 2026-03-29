# RxEpics — Python Implementation Plan

Reactive Streams for EPICS Channel Access, modelled on RxJTango.
Python equivalent using `caproto` + `reactivex` (RxPY v4).

---

## Goal

Wrap EPICS Channel Access (CA) with `Observable[T]` interfaces so that
ReactiveX composition patterns — polling, zipping, sliding average,
backpressure, fluent pipelines — work on EPICS PVs with the same operator
vocabulary as RxJTango.

---

## Technology choices

### CA client: caproto

- Pure Python, no C/libca dependency
- asyncio-native (`caproto.asyncio.client`)
- Supports both one-shot get and subscription (monitor)
- Simple API: `get()`, `subscribe()`, async context manager for lifecycle

### Reactive layer: reactivex (v4)

- `pip install reactivex` — the actively maintained RxPY successor
- Same operator vocabulary as RxJava: `map`, `filter`, `zip`, `buffer`,
  `scan`, `throttle_with_timeout`, `flat_map`, etc.
- Custom sources via `rx.create(subscribe_fn)`
- asyncio integration via `AsyncIOScheduler`

### Dependencies

```
pip install -r requirements.txt
```

---

## Project layout

```
src/rxepics/
  __init__.py
  context.py            Shared caproto async context + channel cache
  channel.py            Single-shot read → Observable (caproto get)
  channel_write.py      Single-shot write → Observable (caproto put)
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

---

## Key differences from RxJTango

### Observable instead of Publisher
`reactivex` uses `Observable[T]` rather than `Publisher<T>`.
Custom sources are created with `rx.create(subscribe_fn)` where
`subscribe_fn(observer, scheduler)` calls `observer.on_next`,
`observer.on_error`, `observer.on_completed`.

### asyncio bridge
caproto is asyncio-native. `reactivex` operators run synchronously by default;
use `AsyncIOScheduler` to bridge:

```python
import asyncio
from reactivex.scheduler.eventloop import AsyncIOScheduler

loop = asyncio.get_event_loop()
scheduler = AsyncIOScheduler(loop)
```

For one-shot reads, wrap the coroutine in a `rx.from_future` or schedule via
`rx.create` + `loop.create_task`.

### Context lifecycle
caproto uses an async context manager per operation by default, but for
reuse across many reads/subscriptions, hold a long-lived
`caproto.asyncio.client.Context` and cache `PVGroup` / channel handles.

```python
# context.py sketch
from caproto.asyncio.client import Context

class EpicsContext:
    _ctx: Context | None = None

    @classmethod
    async def get(cls) -> Context:
        if cls._ctx is None:
            cls._ctx = Context()
        return cls._ctx
```

### No commands
EPICS has no commands. `EpicsClient` has no `execute_command()`. Write to a PV.

### Monitors are preferred
CA subscriptions (`subscribe()`) are first-class. `monitor()` Observable is
the primary streaming primitive; interval polling is a fallback.

---

## Class-by-class implementation guide

### `context.py`
- `EpicsContext.get()` → singleton `caproto.asyncio.client.Context`
- Optional channel cache: `dict[str, caproto channel]`
- Cleanup via `atexit` or explicit `close()`

### `channel.py` — single-shot read

```python
import rx
from rxepics.context import EpicsContext

def read_pv(pv_name: str) -> rx.Observable:
    def subscribe(observer, scheduler):
        async def _get():
            ctx = await EpicsContext.get()
            (pv,) = await ctx.locate(pv_name)
            reading = await pv.read()
            observer.on_next(reading.data[0])
            observer.on_completed()
        asyncio.ensure_future(_get())
    return rx.create(subscribe)
```

### `channel_write.py` — single-shot write
Same pattern; use `pv.write(value)` instead of `pv.read()`.

### `monitor.py` — push Observable

```python
def monitor_pv(pv_name: str) -> rx.Observable:
    def subscribe(observer, scheduler):
        async def _monitor():
            ctx = await EpicsContext.get()
            (pv,) = await ctx.locate(pv_name)
            sub = pv.subscribe()
            async for reading in sub:
                observer.on_next(reading.data[0])
        task = asyncio.ensure_future(_monitor())

        def dispose():
            task.cancel()
        return dispose
    return rx.create(subscribe)
```

### `client.py` — fluent builder

```python
class EpicsClient:
    def read(self, pv_name: str) -> rx.Observable:
        return read_pv(pv_name)

    def monitor(self, pv_name: str) -> rx.Observable:
        return monitor_pv(pv_name)

    def write(self, pv_name: str, value) -> rx.Observable:
        return write_pv(pv_name, value)
```

---

## Test PV stack (Docker)

`docker-compose.yml`:
```yaml
services:
  epics-ioc:
    image: prjemian/synapps:R6-3
    environment:
      - EPICS_CA_ADDR_LIST=localhost
    ports:
      - "5064:5064/tcp"
      - "5065:5065/tcp"
      - "5064:5064/udp"
    volumes:
      - ./test.db:/test.db
    command: softIoc -d /test.db
```

`test.db`:
```
record(ao, "TEST:DOUBLE")   { field(VAL, "0") field(SCAN, ".1 second") }
record(longout, "TEST:LONG")    { field(VAL, "0") }
record(stringout, "TEST:STRING") { field(VAL, "") }
record(calc, "TEST:CALC") {
    field(CALC, "RNDM*1000-500")
    field(SCAN, ".1 second")
}
```

Default PV for examples: `TEST:CALC`

---

## Demo script

| # | Script | Operator | PV |
|---|--------|----------|----|
| 1 | read_pv | single-shot | TEST:DOUBLE, TEST:LONG |
| 2 | poll_pv | interval + flat_map | TEST:CALC |
| 3 | multi_pv_snapshot | zip / combine_latest | all test PVs |
| 4 | pv_stats | take(N) + to_list | TEST:CALC |
| 5 | pv_correlate | zip | TEST:DOUBLE + TEST:LONG |
| 6 | pv_sliding_average | buffer(N,1) + map | TEST:CALC |
| 7 | pv_running_stats | scan + Welford | TEST:CALC |
| 8 | pv_throttle | throttle_with_timeout | TEST:CALC |
| 9 | pv_backpressure | sample / latest | TEST:CALC |
| 10 | pv_pipeline | EpicsClient fluent chain | TEST:CALC → TEST:DOUBLE → TEST:STRING |

---

## Recommended implementation order

1. `context.py` — singleton context, basic `locate` + `read`
2. `channel.py` + `read_pv.py` → verify against real IOC
3. `channel_write.py` + first step of `pv_pipeline.py`
4. `monitor.py` + inline monitor example
5. Remaining examples (port from RxJTango demos, swap operator names)
6. `client.py` fluent builder + full `pv_pipeline.py`
