# Reactive Programming for Tango Controls

**Igor Khokhriakov**
Principal Software Engineer · Hamburg

> RxJTango · spec-compliant Reactive Streams on top of JTango

---

# Slide 1 — Title

## Reactive Programming for Tango Controls

*A reference implementation — and a programming model*

**github.com/Ingvord/RxJTango**

---
Speaker notes:
Skip personal intro — they know you.
Stress "programming model" from the first breath.
RxJTango is the evidence, not the subject.

---

# Slide 2 — Control Systems Are Already Streams

## We just don't model them that way

### What your facility actually produces

```
Device attribute updates
        ↓
Tango event streams  (CHANGE / PERIODIC / ARCHIVE)
        ↓
Alarm streams  ·  telemetry streams
        ↓
Feedback signals  ·  correction commands
```

### How most application code treats it today

```
poll → store → check → write
// loops, threads, shared state,
// try/catch scattered everywhere
```

### Reactive programming treats it as streams from the start

```
source → operator → operator → subscriber
// composable, declarative, back-pressure-aware
// error handling is part of the type system
```

> Reactive programming does not introduce a new concept.
> It gives your system's existing stream nature a proper programming model.

---
Speaker notes:
This slide is the anchor. Before showing any pain points or code, you want
the audience to nod and think "actually… yes, that is what our system looks like."
Once they accept that framing, the rest of the talk lands as a natural consequence.

---

# Slide 3 — Pattern 1: Correlated Multi-Attribute Reads

## Beyond bulk read

> "Every 500 ms, read `current` and `beam_position` from **two different
> devices** — and only process the pair if both arrived in the same polling
> window. Discard if either fails."

### With today's tools…

- **read_attributes()** — reduces round-trips, but only works on the **same device**
- Two sequential reads across devices — a timing gap opens between them
- Sardana environment monitor — if your facility is already on that stack
- Custom thread pair with **CountDownLatch** + careful timeout logic

Most facilities end up implementing variations of this pattern — each
slightly different, each with its own edge cases around failure handling
and timing.

### With Rx — Single.zip()

```java
Flowable.interval(500, MILLISECONDS)
  .flatMapSingle(tick -> Single.zip(

      // Both reads fire in parallel
      read(device1, "current")
          .subscribeOn(Schedulers.io()),
      read(device2, "beam_position")
          .subscribeOn(Schedulers.io()),

      // Combiner: only runs when BOTH complete
      (current, pos) -> process(current, pos)

  ));
```

✓ If either read fails, the pair is silently dropped — never half-processed.
✓ Zero CountDownLatch. Zero shared state.

---
Speaker notes:
Key phrase: "belong together — or not at all." That atomicity guarantee
is what every polling loop silently violates.
Note: zip() itself is sequential; parallelism requires subscribeOn(Schedulers.io())
on each source — make sure to call that out if the audience asks.

---

# Slide 4 — Pattern 2: Real-Time Stream Processing

## Beyond alarm daemons

> "Poll `double_scalar` at 20 Hz, compute a 5-sample sliding average,
> and only write the smoothed value back if it deviates more than 10%
> from the previous write."

### With today's tools…

- **PANIC** — excellent for threshold alerting, but this is not an alarm
- Custom Python script: a `deque`, a counter, a threshold check, a write guard
- A PANIC formula expression — if the formula engine happens to support it
- A Sardana macro — if you're already in that stack

Most facilities end up reimplementing the same scaffolding — sliding
windows, rate control, conditional writes — in slightly different ways
each time.

### With Rx — buffer + distinctUntilChanged

```java
Flowable.interval(50, MILLISECONDS)     // 20 Hz
  .flatMapSingle(read(device, "double_scalar"))

  // Sliding window — no deque, no index arithmetic
  .buffer(5, 1)
  .map(window -> mean(window))

  // Skip write if within 10% of last written value
  .distinctUntilChanged(
      (prev, curr) -> Math.abs(curr - prev) / prev < 0.1
  )

  .flatMapSingle(write(device, "double_scalar_w"));
```

✓ No daemon. No formula DSL. No deque.
✓ Runs anywhere the JVM runs — Java, Kotlin, Groovy, Scala.

---
Speaker notes:
Explicitly name PANIC — "it solves alerting well, and we use it."
The gap is composable stream processing: sliding windows, rate control,
write guards. That is the void Rx fills.

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

4 interfaces. Everything else is implementation.
All RxJTango publishers are **TCK-verified** against this spec.

---

### Multiplatform — Learn Once, Use Everywhere

| Platform | Library |
|----------|---------|
| Java / JVM | RxJava3, Project Reactor |
| Kotlin | Kotlin Flow |
| JavaScript | RxJS |
| Python | RxPY |
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
`zip · merge · buffer · scan · throttleLast · distinctUntilChanged`

---

### Back-Pressure — Flow Control Matters in Control Systems

What happens when producers are faster than consumers?

- Detector emitting events faster than analysis code
- Device bursting change events during a scan
- Multiple devices feeding a single processing pipeline

Explicit strategies:

| Operator | Strategy |
|----------|----------|
| `buffer()` | Accumulate, process in batches |
| `throttleLast()` | Keep freshest value per window |
| `sample()` | Emit latest at fixed intervals |
| `onBackpressureDrop()` | Explicitly drop excess items |

The application **explicitly defines how overload is handled** —
not implicitly through silent buffer overflows.

---
Speaker notes:
Stress multiplatform hard — one paradigm to learn across the whole facility stack.
The backpressure cell resonates immediately with control engineers; they deal
with this exact problem in hardware every day, now there is a software API for it.

---

# Slide 6 — RxJTango Data Flow

## Reference implementation

```
Tango Attribute / Event / Command
        ↓
Reactive Publisher
  RxTangoAttribute · RxTangoAttributeWrite
  RxTangoCommand · RxTangoAttributeChangePublisher
  — all spec-compliant Publisher<T>
        ↓
Rx Operators
  map · zip · merge · buffer · filter · scan · throttleLast
        ↓
Application Logic
  Pure functions — calibration, averaging, threshold checks
        ↓
Commands / Writes / Downstream
  Results written back to devices, forwarded to pipelines,
  logged to telemetry systems
```

Library-agnostic · org.reactivestreams interfaces · TCK-verified · zero build step (jbang)

---

### Real-World Example: Beamline Feedback Loop

Detector intensity → sliding average → drift detection → magnet correction

```java
detectorStream
  // noise reduction — no circular buffer
  .buffer(5, 1)
  .map(window -> mean(window))

  // only act on out-of-range readings
  .filter(v -> outOfRange(v))

  // issue correction command
  .flatMapSingle(write(magnet, "setpoint"));
```

Same pattern, from single beamline feedback to facility-wide telemetry —
without changing the model.

---
Speaker notes:
Move fast on the architecture — the data-flow diagram communicates the idea
in seconds. Spend more time on the beamline example; it is the moment where
the audience connects the abstract model to their actual work.

---

# Slide 7 — Live Demo

## 11 runnable examples · jbang · no build step

### Basic
| Alias | What it shows |
|-------|---------------|
| `read-attribute` | Single-shot Publisher — simplest case |
| `poll` | Continuous read — no loop |

### Coordination
| Alias | What it shows |
|-------|---------------|
| `snapshot` | Parallel reads, concurrent by default |
| `correlate` ★ | **zip** — guaranteed atomic pair |

### Stream Processing
| Alias | What it shows |
|-------|---------------|
| `alarm` ★ | **merge** — isolated per-device failure |
| `sliding-avg` ★ | **buffer(N,1)** — rolling mean, no deque |
| `throttle` | Rate control with **throttleLast** |
| `running-stats` | Live streaming stats with **scan** |

### Composition
| Alias | What it shows |
|-------|---------------|
| `calibrate` | Read → transform → write pipeline |
| `pipeline` ★ | **Showstopper** — fluent 6-step chain |

★ directly address the pain points shown.

```bash
# Start the stack
docker compose up -d    # MariaDB → DatabaseDS → TangoTest

# First example
jbang read-attribute@. tango://localhost:10000/sys/tg_test/1 double_scalar

# The showstopper
jbang pipeline@. tango://localhost:10000/sys/tg_test/1
```

All examples run from **IntelliJ IDEA** with a single click on the
**Run gutter button** — no Maven, no Gradle, no project setup.

**github.com/Ingvord/RxJTango** · Apache-2.0 · Java 11+ · jbang

---
Speaker notes:
The grouping tells the narrative arc — start simple, build coordination,
add stream processing, finish with composition.
If time is short: correlate → alarm → pipeline.
The pipeline is the showstopper; always end on it.
```
