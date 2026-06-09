# Reactive Programming for TINE Controls

**Igor Khokhriakov**
Principal Software Engineer · Hamburg

> RxTine · same ReactiveX idioms — now on DESY's TINE middleware

---

# Slide 1 — Title

## Reactive Programming for TINE Controls

*One programming model. One more control system.*

**github.com/scientific-software-hub/rx-controls-suite**

---
Speaker notes:
TINE audience already knows the pain: `TLink.execute()`, manual callbacks,
scattered thread synchronisation. Skip the long intro — hit the examples fast.

---

# Slide 2 — Pattern 1: Correlated Multi-Property Reads

## Beyond sequential TLink.execute()

> "Every 500 ms, read `CURRENT` from `/HERA/Magnets/QF1` and `XPOS` from
> `/HERA/Diagnostics/BPM01` — and only process the pair if both arrive in
> the same polling window. Discard if either fails."

### With today's tools…

- Two sequential `TLink.executeAndClose()` calls — a timing gap opens between them
- `asyncio.gather` / thread pool + `CountDownLatch` — parallel, but pairing and error handling are manual
- No built-in "atomic multi-property read" primitive in TINE Java

### With Rx — Single.zip()

```java
Flowable.interval(500, MILLISECONDS)
  .flatMapSingle(tick -> Single.zip(

      // Both reads fire in parallel
      TineClient.read("/HERA/Magnets/QF1", "CURRENT")
          .subscribeOn(Schedulers.io()),
      TineClient.read("/HERA/Diagnostics/BPM01", "XPOS")
          .subscribeOn(Schedulers.io()),

      // Only runs when BOTH complete
      (current, pos) -> process(current[0], pos[0])

  ));
```

✓ If either read fails, the pair is silently dropped — never half-processed.
✓ Zero CountDownLatch. Zero shared state.

---

# Slide 3 — Pattern 2: Real-Time Monitor Stream Processing

## Beyond CM_POLL callbacks

> "Monitor `INTENSITY` from `/HERA/Beam/Monitor` at 20 Hz, compute a
> 5-sample sliding average, write back only if it deviates > 10% from last write."

### With today's tools…

- `TLink.attach(CM_POLL, ...)` callback — you manage the ring buffer and write-guard state yourself
- Custom `ArrayDeque` + a counter + a threshold variable — same scaffolding, every time

### With Rx — RxTineMonitor + buffer + distinctUntilChanged

```java
TineClient.monitor("/HERA/Beam/Monitor", "INTENSITY")
  // sliding window — no deque, no index arithmetic
  .buffer(5, 1)
  .map(window -> mean(window))

  // skip write if within 10% of last written value
  .distinctUntilChanged(
      (prev, curr) -> Math.abs(curr - prev) / prev < 0.1
  )

  .flatMapSingle(
      v -> TineClient.write("/HERA/Beam/Corrector", "SETPOINT", v));
```

---

# Slide 4 — Pattern 3: Alarm Fan-In

## Beyond per-device polling loops

> "Watch three RF cavities. When any one reports a fault, notify the operator immediately."

### With today's tools…

- One polling loop per device — or one callback registration per device
- Manual fan-in: shared queue, lock, or third-party aggregator

### With Rx — Flowable.merge()

```java
Flowable.merge(
    TineClient.monitor("/HERA/RF/Cavity01", "STATUS"),
    TineClient.monitor("/HERA/RF/Cavity02", "STATUS"),
    TineClient.monitor("/HERA/RF/Cavity03", "STATUS")
)
.filter(s -> s[0] != STATUS_OK)
.subscribe(alarm -> notifyOperator(alarm));
```

✓ Any one failing device propagates — others continue unaffected.
✓ Add a fourth cavity: one line.

---

# Slide 5 — RxTine Data Flow

## Reference implementation

```
TINE Property (via TLink)
        ↓
Reactive Publisher
  RxTineRead · RxTineWrite  — single-shot
  RxTineMonitor             — push, CM_POLL-backed
  — all spec-compliant Publisher<T>
        ↓
Rx Operators
  map · zip · merge · buffer · filter · distinctUntilChanged
        ↓
Application Logic
  Pure functions — no I/O, no shared state
        ↓
Writes / Downstream
  Results written back to TINE, forwarded to pipelines
```

TDataType always returns arrays — take `[0]` for scalars.
Library-agnostic · org.reactivestreams · TCK-verified · zero build step (jbang)

---

# Slide 6 — Thank You

**github.com/scientific-software-hub/rx-controls-suite**

AGPL-3.0 · Java 11+ · jbang · RxJava3 · TINE Java API
