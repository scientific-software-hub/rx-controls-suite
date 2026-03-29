# RxEpics — Live Demo Playbook

Run these examples from the repo root after installing the package and starting
the test IOC.

---

## 0. Setup

From project root

### Install dependencies

```shell
pip install -r requirements.txt
```

### Start the test IOC

```shell
docker compose up -d
```

Wait ~5 s for the softIoc to initialise, then verify PVs are accessible:

```shell
python -c "
import asyncio
from caproto.asyncio.client import Context
async def check():
    ctx = Context()
    (pv,) = ctx.get_pvs('TEST:CALC')
    r = await pv.read()
    print('TEST:CALC =', r.data[0])
asyncio.run(check())
"
```

### Running examples

Set these two env vars so caproto finds the local IOC (add to your shell profile to avoid repeating):

```shell
export EPICS_CA_ADDR_LIST=localhost
export EPICS_CA_AUTO_ADDR_LIST=NO
```

Then run any example from the repo root:

```shell
PYTHONPATH=src python3 examples/<script>.py [args]
```

---

## 1. Read a PV — single-shot

**The simplest possible Rx interaction.**

`read_pv()` is a single-shot Observable: subscribe once, get one value, done.

```shell
python read_pv.py TEST:DOUBLE TEST:LONG
```

Key code:
```python
# read_pv() is a single-shot Observable — emits one value, then completes.
read_pv("TEST:DOUBLE", ctx).subscribe(
    on_next=lambda v: print(f"TEST:DOUBLE = {v}"),
    on_error=lambda e: print(f"ERROR: {e}"),
)
```

---

## 2. Poll a PV continuously

**From "read once" to "read forever" — without a loop.**

`rx.interval()` ticks every N ms and triggers a fresh read.
`flat_map` turns each tick into an async one-shot read.
The stream runs until Ctrl+C.

```shell
python poll_pv.py TEST:CALC 500
```

Key code:
```python
# interval() emits 0, 1, 2 ... every 500 ms
# flat_map fires one read per tick — no loop, no thread management
rx.interval(timedelta(milliseconds=500), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_pv("TEST:CALC", ctx))
).subscribe(on_next=print)
```

---

## 3. Monitor a PV via CA subscription

**IOC pushes updates — no polling.**

`monitor_pv()` wraps a native CA monitor subscription. Unlike `poll_pv.py`,
the IOC sends updates when the value changes rather than being asked every tick.

```shell
python monitor_pv.py TEST:CALC
```

Key code:
```python
# monitor_pv() wraps pv.subscribe() — the IOC drives the stream.
monitor_pv("TEST:CALC", ctx).subscribe(on_next=print)
```

---

## 4. Parallel snapshot of multiple PVs

**All reads happen at the same time — not one after the other.**

`rx.from_iterable()` streams the PV list.
`flat_map()` issues all reads concurrently.
`to_list()` waits for every read to complete before emitting the snapshot.

One-shot:

```shell
python multi_pv_snapshot.py TEST:DOUBLE TEST:LONG TEST:STRING
```

Continuous (repeat every 2 s):

```shell
python multi_pv_snapshot.py 2000 TEST:DOUBLE TEST:LONG TEST:STRING
```

Key code:
```python
rx.from_iterable(pv_names).pipe(
    ops.flat_map(lambda name: read_pv(name, ctx).pipe(
        ops.map(lambda v, n=name: f"  {n} = {v}"),
        ops.catch(lambda e, _, n=name: rx.of(f"  {n} ! ERROR: {e}")),
    )),
    ops.to_list(),
)
```

---

## 5. Zip two PVs

**Two PVs read simultaneously on every tick — result always coherent.**

`rx.zip(obs1, obs2)` issues both reads concurrently and combines their results
only when BOTH complete — the pair is never half-delivered.

```shell
python zip_pvs.py TEST:DOUBLE TEST:LONG 500
```

Key code:
```python
rx.interval(timedelta(milliseconds=500), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: rx.zip(
        read_pv("TEST:DOUBLE", ctx),
        read_pv("TEST:LONG", ctx),
    ).pipe(ops.map(lambda pair: f"{pair[0]} | {pair[1]}")))
)
```

---

## 6. Statistics over N samples

**Collect, reduce, report — no loop, no list management in your code.**

`take(N)` limits the stream to exactly N ticks.
`to_list()` accumulates all N values automatically.

```shell
python pv_stats.py TEST:CALC 20 500
```

Arguments: `<pv_name> [samples=20] [interval-ms=500]`

---

## 7. Correlated parallel reads

**Two PVs read simultaneously — guaranteed same-tick coherent pair.**

```shell
python pv_correlate.py TEST:DOUBLE TEST:LONG 500
```

---

## 8. Alarm monitor — fan-in

**N independent polling streams merged into one unified alarm stream.**

Each PV has its own `interval → read → filter` chain.
`rx.merge()` multiplexes them into a single output stream.
A failure on one PV is caught by `catch` — it logs and completes that
sub-stream without affecting the others.

```shell
python alarm_monitor.py 200 500 TEST:CALC TEST:DOUBLE
```

Arguments: `<threshold> <interval-ms> <pv_name> [<pv_name2> ...]`

Key code:
```python
streams = [
    rx.interval(interval, scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        ops.filter(lambda v: abs(v) > threshold),
        ops.map(lambda v, n=pv_name: f"ALARM  {n} = {v:.4f}"),
        ops.catch(lambda e, _: rx.empty()),
    )
    for pv_name in pv_names
]
rx.merge(*streams).subscribe(on_next=print)
```

---

## 9. Calibration pipeline — read → transform → write

**A continuous read-transform-write loop as a single Rx chain.**

`interval → flat_map(read) → map(calibrate) → flat_map(write)`

```shell
python calibration_pipeline.py TEST:CALC TEST:DOUBLE 2.0 10.0 1000
```

Arguments: `<src_pv> <dst_pv> <gain> <offset> [interval-ms=1000]`

---

## 10. Fluent pipeline — read → calibrate → write → confirm

**Six steps. Six PV interactions. Zero callbacks. Zero intermediate variables.**

```shell
python pv_pipeline.py
```

Expected output:
```
  [1] read    TEST:CALC     =  -234.76...
  [2] calibrated            =  471.02...
  [3] wrote   TEST:DOUBLE   =  471.02...
  [4] formatted             =  'calibrated=471.0200'
  [5] wrote   TEST:STRING   =  'calibrated=471.0200'

  Pipeline complete.
  Confirmed on IOC: 'calibrated=471.0200'
```

---

## 11. Throttle — rate control for fast producers

**The IOC updates faster than you need. `sample` bridges the gap — one operator, no sleep, no counter.**

```shell
python pv_throttle.py TEST:CALC 50 1000
```

Arguments: `<pv_name> [poll-ms=50] [display-ms=1000]`

Key code:
```python
rx.interval(timedelta(milliseconds=poll_ms), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_pv(pv_name, ctx)),
    ops.do_action(on_next=count_polled),
    # sample: of all values arriving within each display window,
    # keep only the most recent one and discard the rest.
    ops.sample(timedelta(milliseconds=display_ms), scheduler=scheduler),
)
```

---

## 12. Sliding average — noise reduction with `buffer_with_count`

**A rolling mean over the last N samples. No circular buffer, no index arithmetic.**

`buffer_with_count(N, 1)` emits overlapping windows of N values, stepping forward
by 1 each tick. High-frequency noise averages out; slow trends remain visible.

```shell
python pv_sliding_average.py TEST:CALC 5 400
```

Arguments: `<pv_name> [window=5] [interval-ms=400]` — output starts after the first full window.

Key code:
```python
rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_pv(pv_name, ctx)),
    # buffer_with_count(N, 1): sliding window of N values, step 1
    ops.buffer_with_count(window, 1),
    ops.map(lambda buf: (buf[-1], sum(buf) / len(buf))),  # (raw, smoothed)
)
```

---

## 13. Running statistics — live aggregation with `scan`

**Streaming min/max/mean/stddev that updates after every single sample. O(1) memory.**

`scan()` emits the running accumulation after every value — the stats table
updates live as data arrives. Uses Welford's online algorithm for numerically
stable variance.

Compare with `pv_stats.py`: that script collects N samples into a list and exits.
This one runs indefinitely and never allocates a growing list.

```shell
python pv_running_stats.py TEST:CALC 500
```

Arguments: `<pv_name> [interval-ms=500]`

Key code:
```python
rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_pv(pv_name, ctx)),
    # scan() folds each value into the accumulator and emits a new Stats immediately.
    # Unlike reduce(), scan() never waits for the stream to complete.
    ops.scan(Stats.update, Stats.zero()),
    ops.filter(lambda s: s.n > 0),  # skip the empty seed
)
```

---

## 14. Backpressure — fast producer, slow consumer

**What happens when the IOC produces data faster than you can process it?**

Three strategies:

| Strategy | Behaviour |
|----------|-----------|
| `latest` | Sample the stream at the consumer rate — always fresh data |
| `drop`   | Drop values when the consumer slot is occupied |
| `buffer` | Queue up to N items, then crash — demonstrates the failure mode |

```shell
python pv_backpressure.py TEST:CALC
python pv_backpressure.py TEST:CALC 100 600 --strategy drop
python pv_backpressure.py TEST:CALC 100 600 --strategy buffer --buffer-size 5
```
