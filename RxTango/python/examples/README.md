# rxtango Examples — Live Demo Playbook

All examples require the Tango stack to be running:

```bash
docker compose -f ../java/docker-compose.yml up -d
# Brings up: MariaDB → DatabaseDS:10000 → TangoTest sys/tg_test/1
```

Install the library (from `RxTango/python/`):

```bash
uv venv && uv pip install -e .
```

---

## Basic

### `read_attribute.py` — Single-shot read

```bash
python examples/read_attribute.py
```

**Key operator:** `rx.create` → `run_in_executor(proxy.read_attribute)`

Single value emitted, Observable completes immediately.  The Python equivalent of `caget`.

---

### `poll_attribute.py` — Continuous poll (no loop)

```bash
python examples/poll_attribute.py
```

**Key pattern:** `rx.interval(ms).pipe(ops.flat_map(read_attribute(...)))`

This is the canonical polling idiom: `interval` ticks; `flat_map` fires a fresh single-shot
read on every tick.  No `while True`, no `time.sleep`.

---

### `monitor_attribute.py` — Push events (not in live demo)

```bash
python examples/monitor_attribute.py  # needs Tango event system configured
```

**Key primitive:** `monitor_attribute(device, attr, event="periodic")`

Subscribes to CHANGE / PERIODIC / ARCHIVE events.  Callbacks arrive from the Tango C++
thread and are dispatched back to asyncio via `loop.call_soon_threadsafe`.

> **Note:** Requires a Tango device server with events enabled and reachable zmq ports.
> Not used in the live demo; run separately if your environment supports it.

---

## Coordination

### `zip_attributes.py` — Correlated snapshot ★

```bash
python examples/zip_attributes.py
```

**Key operator:** `rx.zip(read_attribute(a), read_attribute(b))`

Both reads fire **in parallel**.  The pair is emitted only when **both** complete.
If either fails, the pair is silently dropped — never half-processed.

---

### `multi_device_snapshot.py` — Parallel snapshot across devices

```bash
python examples/multi_device_snapshot.py
```

**Key pattern:** `rx.from_iterable(devices).pipe(ops.flat_map(read_attribute))`

Fires all reads concurrently; collects results into a list via `ops.to_list()`.
Per-device errors are recovered with `ops.catch` so the snapshot continues.

---

### `correlate.py` — Continuous correlated reads ★

```bash
python examples/correlate.py
```

**Key pattern:** `interval + flat_map(zip(read1, read2))`

Every tick: two reads fire in parallel, the pair is emitted only when both arrive.
Dropped tick if either read fails — guaranteed atomic pairs only.

---

## Stream Processing

### `alarm_monitor.py` — Alarm fan-in via merge ★

```bash
python examples/alarm_monitor.py [device] [threshold]
```

**Key operators:** `rx.merge(*streams).pipe(ops.filter(...))`

Multiple polling streams merged into one.  Each source fails independently.
The alarm fires as soon as any attribute crosses its threshold.

---

### `sliding_average.py` — Rolling mean (no deque) ★

```bash
python examples/sliding_average.py
```

**Key operators:** `ops.buffer_with_count(N, skip=1)` → `ops.map(mean)`

Overlapping windows of N values, advancing by 1 each tick.
No circular buffer, no index arithmetic — one operator call.

---

### `throttle.py` — Rate control

```bash
python examples/throttle.py
```

**Key operator:** `ops.sample(timedelta(ms))`

Fast producer, slow output rate.  `sample` passes the most recent value
each window, dropping the surplus.  Equivalent to Java's `throttleLast`.

---

### `running_stats.py` — Live streaming statistics

```bash
python examples/running_stats.py
```

**Key operator:** `ops.scan(welford_update, seed=...)`

Welford's online algorithm for running mean and standard deviation.
No history stored — stateful accumulation in one `scan` call.

---

### `stats.py` — Collect N samples, print statistics

```bash
python examples/stats.py [device] [n-samples]
```

**Key operators:** `ops.take(N)` → `ops.to_list()`

Collects exactly N readings, computes min/mean/max/std, exits.

---

### `backpressure.py` — Fast producer, slow consumer

```bash
python examples/backpressure.py
```

RxPY does not implement the Reactive-Streams demand protocol.  This example shows
the practical strategies: `ops.sample` (drop surplus, keep freshest).

---

### `retry.py` — Error recovery

```bash
python examples/retry.py
```

**Key operator:** `ops.retry(n)` inside `flat_map`

Up to N immediate retries per poll tick.  The example also sketches the
exponential-backoff pattern using `ops.catch` + `rx.timer`.

---

### `zip_window.py` — Time-windowed synchronisation

```bash
python examples/zip_window.py
```

**Key operators:** `ops.buffer_with_count(N, skip=N)` + `rx.zip`

Buffers N samples from two streams, then zips the buffers — producing
window-synchronised pairs for batch correlation.

---

## Composition

### `calibration_pipeline.py` — Read → calibrate → write

```bash
python examples/calibration_pipeline.py
```

**Key pattern:** `read → map → flat_map(write) → map → flat_map(write)`

Each step's result feeds the next via `flat_map`.  Six observable steps,
zero shared state.

---

### `pipeline.py` — Fluent TangoClient showstopper ★

```bash
python examples/pipeline.py
```

**Key API:** `TangoClient().read().map().write().map().write().read()`

The fluent builder assembles the same six-step pipeline as `calibration_pipeline.py`
with no explicit `flat_map` — each method adds a step internally.

---

### `fluent_client.py` — TangoClient examples

```bash
python examples/fluent_client.py
```

Three short demos of the `TangoClient` API: read→negate→write,
`execute_command`, and a multi-step read→calibrate→write→read-back chain.

---

## Quick Start

```bash
# 1. Start the Tango stack
docker compose -f RxTango/java/docker-compose.yml up -d

# 2. Install
cd RxTango/python && uv pip install -e .

# 3. First example
python examples/read_attribute.py

# 4. The showstopper
python examples/pipeline.py
```

★ = recommended for live demo
