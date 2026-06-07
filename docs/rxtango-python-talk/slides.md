# Reactive Programming for Tango Controls — Python

**Igor Khokhriakov**
Principal Software Engineer · Hamburg

> rxtango · same reactive idioms as the Java library — now in Python

---

# Slide 1 — Title

## Reactive Programming for Tango Controls
### Python Edition

*One programming model.  Two languages.  Same operator vocabulary.*

**github.com/scientific-software-hub/rx-controls-suite**

---
Speaker notes:
The Java version proved the model works on Tango.
This talk is the Python version — same patterns, same operators, PyTango underneath.
The key message: the ReactiveX vocabulary is language-agnostic.
If you know rx.zip in Python, you already know Single.zip in Java.

---

# Slide 2 — The 2×2 Matrix

## Same model across languages AND platforms

|          | Tango           | EPICS          |
|----------|-----------------|----------------|
| **Java** | RxTango/java ✓  | —              |
| **Python** | **RxTango/python ✓** | RxEpics/python ✓ |

All three use the **same operator vocabulary**:
`zip · merge · buffer · scan · sample · flat_map`

The only difference is the control-system call underneath.

---
Speaker notes:
This is the whole point: you don't learn a new API for each platform.
Once you know the operators, moving between Tango and EPICS, Java and Python,
is a matter of swapping one import line.
Point at the table — three corners filled, one to go.

---

# Slide 3 — Pattern 1: Correlated Multi-Attribute Reads

## Beyond bulk read

> "Every 500 ms, read `current` and `beam_position` from **two different
> devices** — and only process the pair if both arrived in the same polling
> window. Discard if either fails."

### With today's tools…

- **read_attributes()** — reduces round-trips, but only works on the **same device**
- Two sequential reads across devices — a timing gap opens between them
- Custom thread pair with **Lock + asyncio.Event** + careful timeout logic

Most facilities end up implementing variations of this pattern — each
slightly different, each with its own edge cases around failure handling
and timing.

### With Rx — rx.zip()

```python
rx.interval(timedelta(milliseconds=500), scheduler=scheduler).pipe(

    ops.flat_map(lambda _: rx.zip(
        # Both reads fire in parallel
        read_attribute(device1, "current"),
        read_attribute(device2, "beam_position"),
    ))

).subscribe(
    on_next=lambda pair: process(*pair),
    on_error=lambda e: log(e),
    scheduler=scheduler,
)
```

✓ If either read fails, the pair is silently dropped — never half-processed.
✓ Zero Lock. Zero shared state.

---
Speaker notes:
The code is identical in structure to the Java version — interval + flat_map + zip.
Only the API names differ: Single.zip → rx.zip, flatMapSingle → flat_map.
The operator contract is identical.

---

# Slide 4 — Pattern 2: Real-Time Stream Processing

## Beyond alarm daemons

> "Poll `double_scalar` at 20 Hz, compute a 5-sample sliding average,
> and only write the smoothed value back if it deviates more than 10%
> from the previous write."

### With today's tools…

- **PANIC** — excellent for threshold alerting, but this is not an alarm
- Custom Python script: a `deque`, a counter, a threshold check, a write guard
- A Sardana macro — if you're already in that stack

Most facilities end up reimplementing the same scaffolding — sliding
windows, rate control, conditional writes — in slightly different ways
each time.

### With Rx — buffer_with_count + distinct_until_changed

```python
rx.interval(timedelta(milliseconds=50), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_attribute(device, "double_scalar")),

    # Sliding window — no deque, no index arithmetic
    ops.buffer_with_count(count=5, skip=1),
    ops.map(lambda window: sum(window) / len(window)),

    # Skip write if within 10% of last written value
    ops.distinct_until_changed(
        comparer=lambda prev, curr: abs(curr - prev) / (prev or 1e-9) < 0.1
    ),

    ops.flat_map(lambda v: write_attribute(device, "double_scalar_w", v)),
).subscribe(on_next=print, scheduler=scheduler)
```

✓ No daemon. No formula DSL. No deque.
✓ Runs anywhere Python runs.

---
Speaker notes:
buffer_with_count(count=5, skip=1) is identical in semantics to Java's buffer(5, 1).
The API is slightly different — keyword arguments vs positional — but the operator
contract is the same. RxPY v4 follows the same specification as RxJava3.

---

# Slide 5 — Reactive Streams — 2 Minutes

## Not a library. A specification.

**reactive-streams.org** — a four-interface contract:

| Interface | Role |
|-----------|------|
| `Publisher<T>` | Produces items — one method: subscribe() |
| `Subscriber<T>` | onNext / onError / onComplete |
| `Subscription` | Back-pressure: request(n) and cancel() |
| `Processor<T,R>` | Both Publisher and Subscriber |

RxPY v4 follows the **same observable contract** as RxJava3.

---

### Multiplatform — Learn Once, Use Everywhere

| Platform | Library |
|----------|---------|
| Java / JVM | RxJava3, Project Reactor |
| Kotlin | Kotlin Flow |
| JavaScript | RxJS |
| Python | **RxPY (reactivex)** |
| .NET | System.Reactive |
| Swift / iOS | RxSwift |

Python scripts, Java servers, JS dashboards — all talking to the same
devices. **One paradigm across all of them.**

---

### Mental Model

```
source → operator → operator → subscriber
```

Key operators used in demos:
`zip · merge · buffer_with_count · scan · sample · distinct_until_changed`

---

### Back-Pressure — Flow Control Matters in Control Systems

RxPY does not implement the Reactive-Streams demand protocol. Instead:

| Operator | Strategy |
|----------|----------|
| `ops.buffer_with_count()` | Accumulate, process in batches |
| `ops.sample()` | Keep freshest value per window |
| `ops.throttle_with_timeout()` | Rate-limit by time |

The application **explicitly chooses the overload strategy** — no silent overflow.

---
Speaker notes:
Be upfront about the backpressure difference — RxPY doesn't have request(n)/cancel()
like the Reactive Streams spec requires. But the practical strategies are identical.
This is an honest engineering trade-off, not a gap.

---

# Slide 6 — rxtango/python Data Flow

## Reference implementation

```
Tango Device  (PyTango DeviceProxy)
        ↓
rx.create(subscribe) + asyncio.ensure_future + run_in_executor
  read_attribute · write_attribute · execute_command · monitor_attribute
        ↓
RxPY Operators
  map · zip · merge · buffer_with_count · filter · scan · sample
        ↓
Application Logic
  Pure functions — calibration, averaging, threshold checks
        ↓
write_attribute / execute_command / Downstream
```

asyncio-native · `loop.run_in_executor` bridges blocking PyTango calls ·
unit-tested against mocked DeviceProxy (no live device required for tests)

---

### Real-World Example: Beamline Feedback Loop

Detector intensity → sliding average → drift detection → magnet correction

```python
rx.interval(timedelta(milliseconds=50), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_attribute(detector, "intensity")),

    # noise reduction — no circular buffer
    ops.buffer_with_count(count=5, skip=1),
    ops.map(lambda window: sum(window) / len(window)),

    # only act on out-of-range readings
    ops.filter(lambda v: out_of_range(v)),

    # issue correction command
    ops.flat_map(lambda v: write_attribute(magnet, "setpoint", v)),
).subscribe(on_next=log, scheduler=scheduler)
```

Same pattern, from single beamline feedback to facility-wide telemetry —
without changing the model.

---
Speaker notes:
Compare this directly to the Java version — same structure, same operator names
(modulo Python naming conventions). This is the proof that the model is language-independent.

---

# Slide 7 — Live Demo

## Python examples · uv · no build step

### Basic
| Script | What it shows |
|--------|---------------|
| `read_attribute.py` | Single-shot Observable — simplest case |
| `poll_attribute.py` | Continuous read — no loop |

### Coordination
| Script | What it shows |
|--------|---------------|
| `multi_device_snapshot.py` | Parallel reads, concurrent by default |
| `correlate.py` ★ | **zip** — guaranteed atomic pair |

### Stream Processing
| Script | What it shows |
|--------|---------------|
| `alarm_monitor.py` ★ | **merge + filter** — isolated per-device failure |
| `sliding_average.py` ★ | **buffer_with_count(N,1)** — rolling mean, no deque |
| `throttle.py` | Rate control with **sample** |
| `running_stats.py` | Live streaming stats with **scan** |

### Composition
| Script | What it shows |
|--------|---------------|
| `calibration_pipeline.py` | Read → transform → write pipeline |
| `pipeline.py` ★ | **Showstopper** — fluent TangoClient 6-step chain |

★ directly address the real-world patterns shown.

```bash
# Start the stack
docker compose up -d

# First example
python examples/read_attribute.py

# The showstopper
python examples/pipeline.py tango://localhost:10000/sys/tg_test/1
```

---
Speaker notes:
The grouping tells the narrative arc — start simple, build coordination,
add stream processing, finish with composition.
If time is short: correlate → alarm → pipeline.
The pipeline is the showstopper — always end on it.
Note: monitor_attribute.py exists but needs a Tango event system — skip for live demo.
```
