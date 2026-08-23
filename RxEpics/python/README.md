# RxEpics — Reactive Streams for EPICS Channel Access

RxEpics wraps EPICS Channel Access with [`reactivex`](https://rxpy.readthedocs.io/) (RxPY v4) observables, giving Python control engineers the same composable, declarative stream-processing vocabulary used in RxJava3, RxJS, and Kotlin Flow — applied directly to PV reads, writes, and CA monitor subscriptions.

The core claim: EPICS is already a streaming system. Channel Access monitors, DBE_VALUE / DBE_ALARM events, and alarm records are all streams. Most application code treats them as polling loops and callback functions. RxEpics gives that stream nature a proper programming model.

## Contents

- [Design principles](#design-principles)
- [Directory layout](#directory-layout)
- [Quick start](#quick-start)
- [Library API](#library-api)
- [Examples](#examples)
- [Tomography demo](#tomography-demo)
- [Environment variables](#environment-variables)
- [Development setup](#development-setup)

---

## Design principles

**Single-shot vs push.** RxEpics draws a hard line between two kinds of interaction.

`read_pv()` and `write_pv()` are *single-shot*: subscribe once, receive one value, the observable completes. They are the reactive equivalent of `caget` / `caput`. Compose them with `rx.interval()` and `flat_map` to build a polling loop without a loop.

`monitor_pv()` is *push*: it wraps a native CA monitor subscription and emits a value every time the IOC sends a DBE_VALUE update. The IOC drives the stream; nothing polls.

**Library-agnostic.** The public API returns `rx.Observable`. Nothing in the library depends on a specific scheduler, event loop topology, or application framework. You wire up `AsyncIOScheduler` (or any other) at the call site.

**Thin wrapper.** RxEpics adds no caching, no connection pooling beyond what caproto already provides, and no domain logic. The library's job is to turn caproto's async coroutines into lazy, composable observables.

**caproto arrays.** caproto always returns `data` as a numpy array. Every primitive takes `float(reading.data[0])`, so scalars flow through the pipeline as Python floats. If you need array PVs you can call caproto directly and wrap the result in `rx.of()`.

**Resilience — errors as messages, not exceptions that stop the process.**
This is the design principle behind the suite (Khokhriakov et al., *J. Synchrotron
Rad.* 29, 644–653, 2022), and it draws a specific line here: Rx's `on_error` is a
*terminal* notification, so routing a transient failure through it would mean the
failure that ends the monitor. RxEpics instead splits failures by what they mean:

- A **setup** failure (the PV cannot be located, a subscription cannot be created)
  is terminal — the stream really is over — and reaches `on_error`, exactly as
  before.
- A **per-update** failure (an unconvertible payload, a non-normal CA status) is a
  *message*. `monitor_pv` logs it at WARNING and keeps running;
  `monitor_errors(pv, ctx)` carries it as a `PvUpdateError` value on its own
  stream instead, for callers who want to react to it in-band.
- A **connection transition** is likewise a message, on `connection_status(pv, ctx)`
  — never an error.

**Reconnect is caproto's job, not this library's.** A live IOC kill/restart test
(`tests/test_resilience_ioc.py`) proves caproto re-arms a dropped CA subscription
on its own: disconnect is detected in roughly 1–3 s, and the monitor value stream
resumes within seconds to ~15 s of the IOC returning, depending on CA search
backoff timing — with no client-side action. `monitor_pv` needs no reconnect
operator. The single-shot paths (`read_pv`/`write_pv`) *do* complete on failure,
so `retry_with_backoff()` is provided for those.

---

## Directory layout

```
RxEpics/python/
├── src/rxepics/            ← installable library
│   ├── __init__.py         ← public API: read_pv, write_pv, monitor_pv,
│   │                            monitor_errors, connection_status,
│   │                            retry_with_backoff, PvUpdateError,
│   │                            EpicsContext, EpicsClient
│   ├── channel.py          ← read_pv()
│   ├── channel_write.py    ← write_pv()
│   ├── monitor.py          ← monitor_pv(), monitor_errors()
│   ├── errors.py           ← PvUpdateError
│   ├── connection.py       ← connection_status()
│   ├── retry.py            ← retry_with_backoff()
│   ├── context.py          ← EpicsContext singleton
│   └── client.py           ← EpicsClient fluent builder
│
├── examples/               ← 15 standalone scripts, one pattern each
│   ├── README.md           ← detailed per-example documentation
│   ├── poll_pv.py          ← interval → flat_map(read)
│   ├── monitor_pv.py       ← push subscription, no polling
│   ├── multi_pv_snapshot.py
│   ├── pv_correlate.py     ← rx.zip — atomic pair
│   ├── alarm_monitor.py    ← rx.merge — fan-in alarm stream
│   ├── calibration_pipeline.py
│   ├── pv_pipeline.py      ← EpicsClient fluent chain
│   ├── pv_throttle.py      ← ops.sample — rate control
│   ├── pv_sliding_average.py ← ops.buffer_with_count
│   ├── pv_running_stats.py ← ops.scan — online statistics
│   ├── pv_backpressure.py  ← drop / latest / buffer strategies
│   ├── pv_stats.py         ← take(N) → to_list → statistics
│   ├── connection_status.py ← CA link state as a stream
│   ├── retry_pv.py         ← retry_with_backoff on read_pv
│   └── resilient_monitor.py ← values + errors + link state merged
│
├── tests/                  ← pytest suite (fakes-based, fast by default)
│   ├── conftest.py         ← fakes modeling caproto's real asyncio contract
│   ├── ioc.py               ← minimal caproto IOC for the integration test
│   ├── test_monitor.py     ← monitor_pv values, contract regressions, GC survival
│   ├── test_errors.py      ← monitor_errors
│   ├── test_connection.py  ← connection_status
│   ├── test_retry.py       ← retry_with_backoff
│   └── test_resilience_ioc.py ← @pytest.mark.integration: real IOC kill/restart
│
├── demo/tomography/        ← full beamline acquisition demo
│   ├── tomography.db       ← EPICS database: rotation stage, detector,
│   │                            beam diagnostics, shutter, scan state
│   ├── simulator.py        ← Python device simulator (motor motion,
│   │                            detector exposure, Poisson counts)
│   ├── tomography_scan.py  ← reactive scan pipeline + HDF5 + live display
│   ├── explore_scan.ipynb  ← Jupyter notebook for post-scan HDF5 analysis
│   ├── Dockerfile          ← softIoc container (caproto + simulator)
│   └── docker-compose.yml  ← brings up softIoc + simulator together
│
├── docker-compose.yml      ← minimal softIoc for examples (test.db only)
├── test.db                 ← TEST:CALC, TEST:DOUBLE, TEST:LONG, TEST:STRING
├── pyproject.toml          ← hatchling build; installs as `rxepics`
└── requirements.txt        ← caproto[asyncio]>=1.0, reactivex>=4.0
```

---

## Quick start

**Prerequisites:** Docker, Python 3.12+, `uv` (or pip).

### 1. Install the library

```bash
cd RxEpics/python
uv venv
uv pip install -e .
```

Or with pip into an existing environment:

```bash
pip install -e .
```

### 2. Start the test IOC

```bash
docker compose up -d
```

This starts a caproto softIoc exposing four test PVs:

| PV | Type | Description |
|----|------|-------------|
| `TEST:CALC` | `calc` | Random ±500 signal at 10 Hz — the primary test signal |
| `TEST:DOUBLE` | `ao` | Static read/write double |
| `TEST:LONG` | `longout` | Static read/write long |
| `TEST:STRING` | `stringout` | Static read/write string |

### 3. Set CA environment variables

```bash
export EPICS_CA_ADDR_LIST=localhost
export EPICS_CA_AUTO_ADDR_LIST=NO
```

These tell caproto where to find the IOC. Without them, CA broadcast discovery
may not reach a Docker container on Linux. Add them to your shell profile to
avoid repeating.

### 4. Run the first example

```bash
uv run python examples/poll_pv.py TEST:CALC 500
```

Expected output (values vary):

```
TEST:CALC   +312.4183
TEST:CALC   -87.2940
TEST:CALC   +451.0012
^C
```

### 5. Run the showstopper

```bash
uv run python examples/pv_pipeline.py
```

This runs a six-step read → calibrate → write → confirm chain with zero callbacks
and zero intermediate variables.

---

## Library API

All public names are importable from `rxepics` directly:

```python
from rxepics import (
    read_pv, write_pv, monitor_pv, EpicsContext, EpicsClient,
    monitor_errors, connection_status, retry_with_backoff, PvUpdateError,
)
```

### `read_pv(pv_name, ctx) → rx.Observable`

Single-shot read. Emits one `float` value and completes. Errors propagate via
`on_error`. Does not cache the PV handle — every subscription opens a fresh
`ctx.get_pvs()` call.

```python
read_pv("TEST:CALC", ctx).subscribe(
    on_next=lambda v: print(f"value: {v}"),
    on_error=lambda e: print(f"error: {e}"),
)
```

Compose with `rx.interval` for polling:

```python
rx.interval(timedelta(milliseconds=500), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_pv("TEST:CALC", ctx))
).subscribe(on_next=print)
```

### `write_pv(pv_name, value, ctx) → rx.Observable`

Single-shot write. Writes `value` to `pv_name`, then emits the written value
and completes. The written value flowing through makes writes chainable:

```python
read_pv("TEST:CALC", ctx).pipe(
    ops.map(lambda v: abs(v) * 2.0 + 1.5),
    ops.flat_map(lambda v: write_pv("TEST:DOUBLE", v, ctx)),
    ops.flat_map(lambda _: read_pv("TEST:DOUBLE", ctx)),
).subscribe(on_next=print)
```

### `monitor_pv(pv_name, ctx) → rx.Observable`

Push subscription. Wraps `pv.subscribe()` — the IOC drives the stream. The CA
subscription is created lazily on the first subscriber and cleared when the
subscription is disposed.

Unlike `read_pv`, this observable never completes on its own. It runs until
cancelled or until the program exits.

```python
monitor_pv("TEST:CALC", ctx).pipe(
    ops.buffer_with_count(5, 1),
    ops.map(lambda w: sum(w) / len(w)),
).subscribe(on_next=lambda avg: print(f"smoothed: {avg:.4f}"))
```

### `monitor_errors(pv_name, ctx) → rx.Observable`

Push subscription of `PvUpdateError` — one value per per-update failure on
*pv_name* (bad conversion, non-normal CA status). Shares its CA subscription
with `monitor_pv` on the same PV. Never completes; never calls `on_error` for
a per-update failure — only a setup failure is terminal, matching `monitor_pv`.

```python
monitor_errors("TEST:CALC", ctx).subscribe(
    on_next=lambda err: log.warning("bad update: %s", err),
)
```

### `connection_status(pv_name, ctx) → rx.Observable`

Push subscription of `bool` — `True` while *pv_name* is connected over CA.
Emits the current state immediately on subscribe (synthetic `False` if the PV
has never connected), then one value per transition. Never completes.

```python
connection_status("TEST:CALC", ctx).subscribe(on_next=set_link_led)
```

### `retry_with_backoff(max_retries=3, base_delay_ms=500, scheduler=None)`

Operator for `read_pv` / `write_pv`: retries with exponential backoff, then
lets the original error through `on_error` once exhausted. Requires a
scheduler bound to the same loop the source was created on.

```python
read_pv("TEST:CALC", ctx).pipe(
    retry_with_backoff(max_retries=5, scheduler=scheduler)
).subscribe(on_next=print, on_error=print)
```

### `EpicsContext`

Process-wide singleton `caproto.asyncio.client.Context`. Caches PV handles to
avoid repeated `get_pvs()` lookups across multiple observables.

```python
ctx = await EpicsContext.get()           # create or return shared context
pv  = await EpicsContext.get_pv("TEST:CALC")  # cached handle
```

Suitable for long-running services. For short scripts, constructing
`Context()` directly (as the examples do) is simpler.

### `EpicsClient`

Fluent builder that chains read / map / write steps into a single lazy pipeline.
Steps do not execute until `subscribe()` is called. The result of each step is
the input of the next.

```python
await EpicsClient(ctx) \
    .read("TEST:CALC") \
    .map(lambda v: abs(v) * 2.0 + 1.5) \
    .write("TEST:DOUBLE") \
    .map(lambda v: f"calibrated={v:.4f}") \
    .write("TEST:STRING") \
    .read("TEST:STRING") \
    .subscribe(on_next=print, on_completed=done.set, scheduler=scheduler)
```

`monitor()` is supported as the first step only (it starts a push subscription
rather than a single-shot read). Chaining `monitor()` after another step raises
`RuntimeError`.

Available methods: `read(pv)`, `write(pv, value=None)`, `monitor(pv)`,
`map(fn)`, `subscribe(on_next, on_error, on_completed, scheduler)`.

---

## Examples

Each script in `examples/` demonstrates one operator or composition pattern.
All scripts take PV names and tuning parameters as command-line arguments so
they run against any IOC without code changes.

See [`examples/README.md`](examples/README.md) for full usage, expected output,
and annotated key code for every example.

| Script | Pattern | Key operators |
|--------|---------|---------------|
| `poll_pv.py` | Continuous polling without a loop | `interval · flat_map` |
| `monitor_pv.py` | IOC-driven push stream | `monitor_pv` |
| `multi_pv_snapshot.py` | Parallel snapshot of N PVs | `from_iterable · flat_map · to_list` |
| `pv_correlate.py` | Atomic pair — both PVs from the same tick | `zip` |
| `alarm_monitor.py` | Fan-in alarm stream across N PVs | `merge · filter · catch` |
| `calibration_pipeline.py` | Continuous read → calibrate → write loop | `interval · flat_map · map` |
| `pv_pipeline.py` | Fluent 6-step chain via EpicsClient | `EpicsClient` |
| `pv_throttle.py` | Rate control — fast producer, slow consumer | `sample` |
| `pv_sliding_average.py` | Rolling mean over last N samples | `buffer_with_count · map` |
| `pv_running_stats.py` | Live streaming statistics, O(1) memory | `scan` |
| `pv_backpressure.py` | Explicit overload strategies | `sample · filter · buffer` |
| `pv_stats.py` | Collect N samples, compute statistics, exit | `take · to_list` |
| `connection_status.py` | CA link state as a stream | `connection_status` |
| `retry_pv.py` | Resilient single-shot read | `retry_with_backoff` |
| `resilient_monitor.py` | Values + errors + link state, survives an IOC restart | `merge · monitor_errors · connection_status` |

### Operator quick-reference

`buffer_with_count(N, 1)` emits overlapping sliding windows of N values, stepping
forward by 1 per tick. Use it for rolling averages, peak detection, and any
fixed-window computation. The first output appears only after N ticks.

`ops.scan(accumulator, seed)` folds each incoming value into a running accumulator
and emits the result immediately — unlike `reduce()`, it never waits for the stream
to complete. Use it for live statistics, cumulative sums, and any state that must
be visible after every sample.

`rx.zip(obs1, obs2, ...)` issues all observables concurrently and emits a tuple
only when every one has completed. If any observable errors, the combined
observable errors. Use it for correlated multi-PV reads where a half-delivered
pair would be meaningless.

`rx.merge(*streams)` multiplexes N independent observables into one. Each stream
runs in parallel; values appear in arrival order. A `catch` on each sub-stream
isolates failures — one failing PV does not kill the others. Use it for alarm
fan-in across many devices.

`ops.sample(interval)` emits the most recent value once per interval window,
silently dropping all intermediate values. Zero buffering. Use it when a display
or downstream consumer runs slower than the source without introducing
back-pressure.

---

## Tomography demo

`demo/tomography/` is a self-contained beamline acquisition demo that goes beyond
the test-PV examples. It simulates a real tomography beamline: rotation stage,
X-ray detector, beam diagnostics, and shutter — 18 PVs in total.

### What it demonstrates

The scan pipeline in `tomography_scan.py` shows how reactive composition scales
from single operators to a full acquisition sequence:

- **Motor sequencing** — write target → poll readback until settled → proceed.
  No `asyncio.sleep`, no manual timeout logic.
- **Detector trigger + exposure wait** — write ACQUIRE → poll ACQUIRING=1 →
  poll ACQUIRING=0. The same `poll_until()` primitive used throughout.
- **Concurrent diagnostic reads** — `rx.zip` reads counts, beam current, and
  beam position simultaneously after each exposure.
- **Fan-out to two consumers** — `ops.share()` makes the cold scan observable
  hot so both branches see every frame. The HDF5 writer receives every frame.
  The live display receives a throttled view via `ops.sample()`.
- **HDF5 logging** — every projection is written to a structured dataset with
  timestamp, angle, counts, and beam diagnostics. The file is pre-allocated
  before the scan starts.

The key insight: two consumers with different performance requirements share one
source without coordination code. `sample()` on the display branch drops frames
when the terminal cannot keep up. The writer branch never misses a frame. No
locks, no queues, no shared state between branches.

### Running the tomography demo

```bash
cd demo/tomography
docker compose up -d --build   # starts softIoc + device simulator
```

Wait ~5 s for the simulator to connect, then:

```bash
# Table output (default)
python tomography_scan.py --projections 36 --exposure-ms 50

# ASCII animation
python tomography_scan.py --projections 36 --exposure-ms 50 --ascii
```

The scan saves a timestamped HDF5 file (`scan_YYYYMMDD_HHMMSS.h5`) in the
`demo/tomography/` directory.

### Exploring the HDF5 output

Open `explore_scan.ipynb` in Jupyter to inspect the saved scan data:

```bash
jupyter notebook demo/tomography/explore_scan.ipynb
```

The notebook loads the HDF5 file, plots beam current and detector counts vs
angle, and computes a sinogram from the counts column.

### Beamline PVs

| PV | Type | Description |
|----|------|-------------|
| `TOMO:ROT:VAL` | `ao` | Rotation stage target (deg) |
| `TOMO:ROT:RBV` | `ai` | Rotation stage readback (deg) |
| `TOMO:ROT:SPEED` | `ao` | Stage speed (deg/s) |
| `TOMO:ROT:MOVN` | `bi` | Moving flag (0=stopped, 1=moving) |
| `TOMO:DET:EXPOSURE` | `ao` | Detector exposure time (ms) |
| `TOMO:DET:ACQUIRE` | `bo` | Acquisition trigger |
| `TOMO:DET:ACQUIRING` | `bi` | Acquiring flag |
| `TOMO:DET:COUNTS` | `ai` | Integrated photon counts |
| `TOMO:BEAM:CURRENT` | `calc` | Beam current ~500 mA with noise |
| `TOMO:BEAM:POSX` | `calc` | Beam centroid X (mm) |
| `TOMO:BEAM:POSY` | `calc` | Beam centroid Y (mm) |
| `TOMO:SHUTTER:OPEN` | `bo` | Shutter control |
| `TOMO:SHUTTER:OPEN:STS` | `bi` | Shutter status readback |
| `TOMO:SCAN:STATUS` | `mbbi` | Scan state (IDLE/RUNNING/DONE/ABORTED) |
| `TOMO:SCAN:CUR_ANGLE` | `ai` | Current scan angle |
| `TOMO:SCAN:CUR_PROJ` | `longin` | Current projection index |

---

## Environment variables

| Variable | Required | Description |
|----------|----------|-------------|
| `EPICS_CA_ADDR_LIST` | Yes (Docker) | Space-separated list of CA broadcast addresses. Set to `localhost` when the IOC runs in a Docker container with `network_mode: host`. |
| `EPICS_CA_AUTO_ADDR_LIST` | Yes (Docker) | Set to `NO` when `EPICS_CA_ADDR_LIST` is explicit. |
| `EPICS_CA_SERVER_PORT` | No | CA server port (default 5064). |

For a system IOC reachable on the local network, CA broadcast discovery usually
works without setting these. For Docker containers, both variables are required
because `network_mode: host` exposes the IOC on the loopback interface only.

Add to your shell profile for persistent configuration:

```bash
export EPICS_CA_ADDR_LIST=localhost
export EPICS_CA_AUTO_ADDR_LIST=NO
```

---

## Development setup

```bash
cd RxEpics/python
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"    # installs rxepics + development extras if defined
```

Or with uv (no activation needed):

```bash
uv pip install -e .
uv run python examples/poll_pv.py TEST:CALC
```

The `.venv/` directory is gitignored. Never install into the system Python.

### Running examples without installing

If you prefer not to install the package, prefix with `PYTHONPATH`:

```bash
PYTHONPATH=src python examples/poll_pv.py TEST:CALC 500
```

### Running the tests

```bash
uv pip install -e ".[dev]"
pytest RxEpics/python/tests -q                # fast: fakes-based unit tests, ~2s
pytest RxEpics/python/tests -q -m integration  # slow: spawns a real IOC, ~5-30s
```

Plain `pytest` (no `-m`) excludes the `integration`-marked test by default —
see `pyproject.toml`. The fakes in `tests/conftest.py` model caproto's real
asyncio-client contract (2-arg weakref-backed callbacks, an async
`Subscription.clear()`, `connection_state_callback`'s replay-on-subscribe
behavior) deliberately, not for convenience — they are what caught the two
resilience bugs this library's monitor path originally had.

### Package structure

The library is structured as a standard `src/` layout. `pyproject.toml` uses
`hatchling` as the build backend. The package name is `rxepics`; the
import name is also `rxepics`.

```python
# All public names available at the top level:
from rxepics import read_pv, write_pv, monitor_pv, EpicsContext, EpicsClient
```

---

## Relation to rx-controls-suite

RxEpics is one sub-project in [rx-controls-suite](../../README.md), a monorepo
demonstrating the same ReactiveX operator vocabulary across multiple control
system frameworks.

| Sub-project | Language | Control system | Transport |
|-------------|----------|----------------|-----------|
| `RxEpics/python` | Python 3.12+ | EPICS | Channel Access (caproto) |
| `RxTango/java` | Java 11+ | Tango Controls | JTango / ezTangoAPI |
| `RxTine/java` | Java 11+ | TINE (DESY) | TINE Java client |

The operator patterns — `zip` for correlated reads, `buffer_with_count` for
sliding windows, `merge` for alarm fan-in — are identical across all three.
The only difference is the CA / Tango / TINE call underneath.
