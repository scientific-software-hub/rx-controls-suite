# rxdectris — Reactive Streams for DECTRIS Detectors (Python)

Wraps a DECTRIS **SIMPLON** REST + Stream V2 API with `Observable[T]` via
[reactivex](https://rxpy.readthedocs.io/) (RxPY v4) — the same operator
vocabulary as [`rxtango/python`](../../RxTango/python) and
[`rxepics/python`](../../RxEpics/python), applied to a detector instead of a
facility control system.

```python
import asyncio
from reactivex.scheduler.eventloop import AsyncIOScheduler
from rxdectris import DetectorContext, acquire_series

async def main():
    loop      = asyncio.get_running_loop()
    scheduler = AsyncIOScheduler(loop)
    done      = asyncio.Event()

    ctx = await DetectorContext.get("http://localhost:8080")

    acquire_series(ctx, frames=20, count_time=0.01).subscribe(
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
# From the RxDectris/python directory:
uv venv
uv pip install -e .
```

**Prerequisites:** Python 3.10+. Talks to a real DCU or to
[`demo/dectris-integration/simplon_sim`](../../demo/dectris-integration/simplon_sim)
(`docker compose up -d simplon-sim` from that directory).

---

## Library API

All primitives return a plain `rx.Observable` — compose them with any
standard RxPY operator. `ctx` is a `DetectorContext`, obtained once per DCU
with `await DetectorContext.get(base_url)`.

| Function | SIMPLON endpoint | Shot |
|---|---|---|
| `read_config(param, ctx)` | `GET /detector/api/1.8.0/config/<param>` | single |
| `write_config(param, value, ctx)` | `PUT /detector/api/1.8.0/config/<param>` | single |
| `read_status(param, ctx)` | `GET /detector/api/1.8.0/status/<param>` | single |
| `monitor_state(ctx, poll_ms=500)` | polls `status/state` | push |
| `send_command(name, ctx, argin=None)` | `PUT /detector/api/1.8.0/command/<name>` | single |
| `initialize` / `arm` / `trigger` / `disarm` / `abort` / `cancel` | same, one per verb | single |
| `configure_stream(ctx)` | `PUT /stream/api/1.8.0/config/{format,mode}` | single |
| `stream2(ctx)` | Stream V2 socket (ZeroMQ PULL, CBOR, port 31001) | push |
| `monitor_images(ctx, mode="next"\|"monitor")` | `GET /monitor/api/1.8.0/images/<mode>` | push |
| `acquire_series(ctx, frames, count_time, ...)` | the full lifecycle, see below | push |

### `read_config` / `write_config`

```python
read_config("count_time", ctx).subscribe(on_next=print)
# -> {"min": 0.018, "max": 3600, "value": 0.5, "value_type": "float", "access_mode": "rw", "unit": "s"}

write_config("count_time", 0.01, ctx).subscribe(on_next=print)
# -> ["count_time", "frame_time"]   (SIMPLON keeps the config internally consistent)
```

### `initialize` / `arm` / `trigger` / `disarm` / `abort` / `cancel`

Each is `send_command(name, ctx)` under the hood. `arm`/`disarm`/`abort`/
`cancel` emit a `sequence_id`; `initialize`/`trigger` emit `None` — SIMPLON
gives them no response body, only the HTTP status matters.

```python
arm(ctx).subscribe(on_next=lambda seq: print("armed, sequence", seq))
```

An illegal transition (e.g. `trigger` before `arm`) raises
`DetectorStateError` via `on_error` — mirrors the DCU's own behaviour rather
than silently no-opping.

### `stream2` — Stream V2

Push Observable over the real wire format: ZeroMQ PUSH on the DCU (port
`31001`), PULL here, CBOR-encoded `start` / `image` × N / `end` messages.
Never completes on its own — bound it yourself, e.g.:

```python
stream2(ctx).pipe(
    ops.take_while(lambda m: not isinstance(m, SeriesEnd), inclusive=True),
).subscribe(on_next=print)
```

`acquire_series` does exactly this internally.

### `monitor_images` — the Monitor subsystem

SIMPLON's own backpressure split, over plain HTTP: `mode="next"` pops the
oldest buffered frame (every frame, in order); `mode="monitor"` returns only
the newest, non-destructively — the documentation itself says not to use
anything else above 10 Hz. That's `share()` + `sample()` already built into
the product.

### `DetectorContext`

```python
ctx = await DetectorContext.get("http://localhost:8080")
await ctx.aclose()
```

One context per DCU base URL, cached — the locator the tests patch.

### `DectrisClient` — fluent builder

Same shape as `TangoClient`/`EpicsClient`:

```python
DectrisClient(ctx) \
    .read("count_time") \
    .execute("arm") \
    .execute("trigger") \
    .subscribe(on_next=print, on_completed=done.set, scheduler=scheduler)
```

### `acquire_series(ctx, frames, count_time, frame_time=None, trigger_mode="ints")`

The detector-lifecycle recipe: configure → enable stream → subscribe to
`stream2` *before* `arm` (arm is what emits `start` — arming first races the
socket) → `arm` → `trigger` (internal trigger modes only) → re-emit every
Stream V2 message until `SeriesEnd` → `disarm`.

Teardown is unconditional and exactly-once: disposal or any error issues
`abort`; the clean path issues `disarm`. The detector always lands back in
`idle`.

```python
acquire_series(ctx, frames=100, count_time=0.01).subscribe(
    on_next=lambda msg: print(type(msg).__name__, msg),
    on_completed=lambda: print("series complete"),
)
```

---

## Running Tests

```bash
uv pip install -e ".[dev]"
pytest -v
```

Tests use a hand-written fake `DetectorContext` (`httpx.MockTransport` for
the REST calls, an in-memory queue for the Stream V2 socket) — no running
simulator or network required.

---

## What is simulated, and what is not

`demo/dectris-integration/simplon_sim` implements enough of SIMPLON 1.8 to
drive this wrapper's lifecycle and stream honestly, against the *public*
[SIMPLON 1.8 API documentation, v3.5](https://media.dectris.com/) — nothing
here is derived from DECTRIS internal source.

| Simulated faithfully | Simplified for the demo |
|---|---|
| URL grammar, detector state enum, command semantics (`abort` vs `cancel`) | Real diffraction physics — images are a small synthetic blob, not detector electronics |
| Stream V2 wire format: ZeroMQ PUSH/PULL on 31001, CBOR, `start`/`image`/`end` field names | Monitor subsystem returns JSON frame metadata, not real `.tif` with DECTRIS private TIFF tags |
| Config-write cascades (`count_time` forcing `frame_time` up) | Only one detector model/geometry; no multi-threshold, no ROI |
| The single documented lifecycle sequence (init → configure → enable interface → arm → trigger → disarm) | `configure` and `test` states exist in the API's enum but are not driven here |

---

## Relation to rx-controls-suite

| Sub-project | Platform | Language | Single-shot | Push | Commands |
|---|---|---|---|---|---|
| `RxTango/python` | Tango | Python | `read_attribute` | `monitor_attribute` | `execute_command` ✓ |
| `RxEpics/python` | EPICS | Python | `read_pv` | `monitor_pv` | — |
| **`RxDectris/python`** | **DECTRIS SIMPLON** | **Python** | **`read_config`** | **`stream2`** | **`send_command`** ✓ |

Same operator vocabulary. Different control system underneath — this time
the platform on the other end is a detector, not a facility.

---

## License

AGPL-3.0 for open/non-commercial use. See [`LICENSE`](../../LICENSE).
Commercial license: [`LICENSE-COMMERCIAL.md`](../../LICENSE-COMMERCIAL.md).
