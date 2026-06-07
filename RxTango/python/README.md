# rxtango — Reactive Streams for Tango Controls (Python)

Wrap [PyTango](https://pytango.readthedocs.io/) (`DeviceProxy`) with
`Observable[T]` via [reactivex](https://rxpy.readthedocs.io/) (RxPY v4).

The **same ReactiveX operator vocabulary** that drives
[rxtango/java](../java/) and [rxepics/python](../../RxEpics/python/) works
identically here — `zip`, `buffer_with_count`, `scan`, `merge`, `sample`,
`flat_map` — with a thin Tango wrapper underneath.

```python
import asyncio
import reactivex as rx
import reactivex.operators as ops
from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxtango import read_attribute, TangoClient

device = "tango://localhost:10000/sys/tg_test/1"

async def main():
    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    # Single read
    read_attribute(device, "double_scalar").subscribe(
        on_next=print,
        on_completed=done.set,
        scheduler=scheduler,
    )
    await done.wait()

asyncio.run(main())
```

---

## Installation

```bash
# From the RxTango/python directory:
uv venv
uv pip install -e .
```

**Prerequisites:** PyTango 9.3+, Python 3.10+, a running Tango database.

Start the test device server:

```bash
docker compose -f ../java/docker-compose.yml up -d
# Brings up: MariaDB → DatabaseDS:10000 → TangoTest sys/tg_test/1
```

---

## Library API

All primitives return a plain `rx.Observable` — compose them with any
standard RxPY operator.

### `read_attribute(device, name) → Observable`

Single-shot attribute read.  Emits `DeviceAttribute.value` and completes.

```python
read_attribute(device, "double_scalar").subscribe(on_next=print, ...)
```

### `write_attribute(device, name, value) → Observable`

Single-shot attribute write.  **Re-emits the written value** so writes can
be chained:

```python
read_attribute(device, "double_scalar").pipe(
    ops.map(lambda v: abs(v) * 2.0),
    ops.flat_map(lambda v: write_attribute(device, "double_scalar_w", v)),
).subscribe(on_next=print, ...)
```

### `execute_command(device, name, argin=None) → Observable`

Single-shot command execution.  Emits the command output (argout).

```python
execute_command(device, "Status").subscribe(on_next=print, ...)
```

*Tango-specific — EPICS has no commands.*

### `monitor_attribute(device, name, event="change") → Observable`

Push Observable backed by Tango event subscription (CHANGE / PERIODIC /
ARCHIVE).  Never completes; dispose to unsubscribe.

```python
monitor_attribute(device, "double_scalar", event="periodic").subscribe(
    on_next=print,
)
```

> **Note:** Requires a Tango event system with reachable zmq ports.

### `TangoContext` — DeviceProxy cache

```python
proxy = TangoContext.get_proxy("tango://localhost:10000/sys/tg_test/1")
TangoContext.close()   # release all cached proxies
```

### `TangoClient` — Fluent builder

```python
TangoClient() \
    .read(device, "double_scalar") \
    .map(lambda v: abs(v) * 2.0 + 1.5) \
    .write(device, "double_scalar_w") \
    .execute(device, "Status") \
    .subscribe(on_next=print, on_completed=done.set, scheduler=scheduler)
```

---

## Key Patterns

### Polling — no loop, no thread

```python
rx.interval(timedelta(milliseconds=500), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
).subscribe(on_next=print, ...)
```

### Correlated reads (zip)

Both reads fire in parallel; pair emitted only when **both** complete:

```python
rx.zip(
    read_attribute(device, "current"),
    read_attribute(device, "beam_position"),
).subscribe(on_next=lambda pair: process(*pair), ...)
```

### Sliding average

```python
rx.interval(...).pipe(
    ops.flat_map(lambda _: read_attribute(device, "value")),
    ops.buffer_with_count(count=5, skip=1),
    ops.map(lambda buf: sum(buf) / len(buf)),
)
```

### Alarm fan-in

```python
rx.merge(poll("device1", "current"), poll("device2", "current")).pipe(
    ops.filter(lambda v: v > THRESHOLD)
).subscribe(on_next=alarm, ...)
```

---

## Running Tests

```bash
uv pip install -e ".[dev]"
pytest -v
```

Tests use a mocked `DeviceProxy` — no live Tango device required.

---

## Examples

See [`examples/README.md`](examples/README.md) for a full playbook.

Quick start:

```bash
python examples/read_attribute.py
python examples/poll_attribute.py
python examples/correlate.py
python examples/pipeline.py   # ← the showstopper
```

---

## Architecture

```
Tango device  (DeviceProxy)
        ↓
rx.create(subscribe) + asyncio.ensure_future + run_in_executor
        ↓
Observable (read_attribute / write_attribute / execute_command / monitor_attribute)
        ↓
RxPY operators: map · zip · merge · buffer_with_count · scan · sample
        ↓
Application logic (calibration, alarming, feedback)
        ↓
write_attribute / execute_command / downstream
```

---

## Relation to rx-controls-suite

| Sub-project | Platform | Language | Single-shot | Push | Commands |
|---|---|---|---|---|---|
| `RxTango/java` | Tango | Java | `RxTangoAttribute` | `RxTangoAttributeChangePublisher` | `RxTangoCommand` ✓ |
| **`RxTango/python`** | **Tango** | **Python** | **`read_attribute`** | **`monitor_attribute`** | **`execute_command`** ✓ |
| `RxEpics/python` | EPICS | Python | `read_pv` | `monitor_pv` | — |

Same operator vocabulary.  Different control system underneath.

---

## License

AGPL-3.0 for open/non-commercial use.  See [`LICENSE`](../../LICENSE).
Commercial license: [`LICENSE-COMMERCIAL.md`](../../LICENSE-COMMERCIAL.md).
