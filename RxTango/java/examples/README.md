# RxJTango — Live Demo Playbook

Run these examples directly from IntelliJ IDEA using the **Run** gutter button
next to each `shell` code block, or paste them into a terminal.

All examples target the local TangoTest device started by `docker compose up -d`
in the repo root.

---

## 0. Start the stack

Three containers: MariaDB → Tango Database Server → TangoTest (`sys/tg_test/1`).

```shell
cd ..
docker compose up -d
```

Wait ~10 s for health checks to propagate, then confirm all three are `healthy`:

```shell
docker compose ps
```

---

## 1. Read an attribute

**The simplest possible Rx interaction.**

`RxTangoAttribute` is a `Publisher<T>` — subscribe once, get one value, done.
Here we use `Flowable.fromPublisher()` as a bridge to RxJava3, then
`blockingSubscribe` to drive it from `main()`.

Read two attributes in a single call:

```shell
jbang ReadAttribute.java \
  tango://localhost:10000/sys/tg_test/1 double_scalar long_scalar
```

Key code:
```java
// RxTangoAttribute is a single-shot Publisher<T>.
// Flowable.fromPublisher() bridges it into RxJava3's operator set.
Flowable.fromPublisher(new RxTangoAttribute<>(device, attr))
    .blockingSubscribe(
        value -> System.out.println(attr + " = " + value),
        err   -> System.err.println(attr + " ERROR: " + err.getMessage())
    );
```

---

## 2. Poll an attribute continuously

**From "read once" to "read forever" — without a loop.**

`Flowable.interval()` ticks every N milliseconds and triggers a fresh read.
`flatMapSingle` turns each tick into an async single-item read.
The stream runs until you press Ctrl+C.

```shell
jbang PollAttribute.java \
  tango://localhost:10000/sys/tg_test/1 double_scalar 500
```

Key code:
```java
// interval() emits Long(0), Long(1), Long(2) ... every 500 ms
// flatMapSingle() fires one read per tick and collects its result
// No loop. No thread management. No counter.
Flowable.interval(500, TimeUnit.MILLISECONDS)
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(device, attr))
                .firstOrError()
    )
    .blockingSubscribe(
        v   -> System.out.println(v),
        err -> System.err.println("ERROR: " + err.getMessage())
    );
```

---

## 3. Parallel snapshot of multiple attributes

**All reads happen at the same time — not one after the other.**

`Flowable.fromIterable()` turns a list of targets into a stream.
`flatMapSingle()` with its default concurrency issues all reads concurrently.
`toList()` waits for every read to complete before emitting the snapshot.

One-shot snapshot of three attributes:

```shell
jbang MultiDeviceSnapshot.java \
  tango://localhost:10000/sys/tg_test/1 double_scalar \
  tango://localhost:10000/sys/tg_test/1 long_scalar \
  tango://localhost:10000/sys/tg_test/1 string_scalar
```

Continuous snapshot every 2 seconds (first arg is the interval):

```shell
jbang MultiDeviceSnapshot.java 2000 \
  tango://localhost:10000/sys/tg_test/1 double_scalar \
  tango://localhost:10000/sys/tg_test/1 long_scalar \
  tango://localhost:10000/sys/tg_test/1 string_scalar
```

Key code:
```java
// fromIterable streams the target list one item at a time.
// flatMapSingle fires one async read per target — all run in parallel.
// onErrorReturn isolates failures: one bad device doesn't kill the snapshot.
// toList() collects all results and emits them as a single List<String>.
Flowable.fromIterable(targets)
    .flatMapSingle(t ->
        Flowable.fromPublisher(new RxTangoAttribute<>(t.device(), t.attribute()))
                .firstOrError()
                .map(v -> String.format("  %-40s = %s", t.attribute(), v))
                .onErrorReturn(e -> String.format("  %-40s ! ERROR: %s",
                        t.attribute(), e.getMessage()))
    )
    .toList()
    .blockingSubscribe(
        lines -> { System.out.println("Snapshot @ " + Instant.now()); lines.forEach(System.out::println); },
        err   -> System.err.println("Fatal: " + err.getMessage())
    );
```

---

## 4. Statistics over N samples

**Collect, reduce, report — with no loop and no list management in your code.**

`take(N)` limits the stream to exactly N ticks.
`toList()` accumulates all N values automatically.
Then one pass over the list computes min/max/mean/stddev.

```shell
jbang TangoTestStats.java \
  tango://localhost:10000/sys/tg_test/1 20 500
```

Arguments: `<device> [samples=20] [interval-ms=500]`

Key code:
```java
// interval + take(N): emit exactly N ticks, then complete automatically.
// flatMapSingle: one RxTangoAttribute read per tick.
// doOnNext: print each sample as it arrives (live progress).
// toList: the Rx operator handles list allocation and synchronization.
// blockingGet: drive the whole chain from main() and return the List<Double>.
List<Double> samples = Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    .take(n)
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                .firstOrError()
                .map(v -> ((Number) v).doubleValue())
    )
    .doOnNext(v -> System.out.printf("  [%2d]  %+.6f%n", counter.incrementAndGet(), v))
    .toList()
    .blockingGet();
```

---

## 5. Correlated parallel reads

**Two attributes read simultaneously on every tick — guaranteed to be from the same moment.**

Sequential reads (`read A; read B`) are vulnerable to a value update between
the two calls — the pair is torn. `Single.zip()` issues both reads in parallel
and delivers them together only when both have arrived.

```shell
jbang TangoTestCorrelate.java \
  tango://localhost:10000/sys/tg_test/1 500
```

Arguments: `<device> [interval-ms=500]`  — runs until Ctrl+C.

Key code:
```java
// Single.zip fires both reads in parallel and combines their results.
// The combiner lambda only runs when BOTH Singles complete successfully.
// If either read fails, zip propagates the error — the pair is never half-delivered.
Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    .flatMapSingle(tick -> Single.zip(
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                .firstOrError()
                .map(v -> ((Number) v).doubleValue()),
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "long_scalar"))
                .firstOrError()
                .map(v -> ((Number) v).longValue()),
        // combiner: only called when both reads complete
        (d, l) -> String.format("%+14.4f  %14d  %+.4f", d, l, d - l)
    ))
    .blockingSubscribe(System.out::println, err -> System.err.println("ERROR: " + err));
```

---

## 6. Alarm monitor — fan-in

**N independent polling streams merged into one unified alarm stream.**

Each device has its own `interval → read → filter` chain.
`Flowable.merge()` multiplexes them into a single output stream.
A failure on one device is caught by `onErrorResumeNext` — it logs and completes
that sub-stream without affecting the others.

```shell
jbang AlarmMonitor.java 200 500 \
  tango://localhost:10000/sys/tg_test/1 double_scalar \
  tango://localhost:10000/sys/tg_test/1 long_scalar
```

Arguments: `<threshold> <interval-ms> <device> <attr> [<device> <attr> ...]`  — Ctrl+C to stop.

Key code:
```java
// Build one polling+filtering stream per target.
List<Flowable<String>> streams = new ArrayList<>();
for (Target t : targets) {
    Flowable<String> stream = Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
        .flatMapSingle(tick ->
            Flowable.fromPublisher(new RxTangoAttribute<>(t.device(), t.attribute()))
                    .firstOrError()
                    .map(v -> ((Number) v).doubleValue())
        )
        // filter: only pass values that exceed the threshold
        .filter(v -> Math.abs(v) > threshold)
        .map(v -> String.format("ALARM  [%s]  %s = %.4f", Instant.now(), t.attribute(), v))
        // isolate: a stream error logs and terminates only this sub-stream
        .onErrorResumeNext(err -> {
            System.err.printf("Stream error for %s: %s — continuing%n", t.device(), err.getMessage());
            return Flowable.empty();
        });
    streams.add(stream);
}

// merge() interleaves all streams into one; each alarm line is printed as it arrives.
Flowable.merge(streams).blockingSubscribe(System.out::println, ...);
```

---

## 7. Calibration pipeline — read → transform → write

**A continuous read-transform-write loop expressed as a single Rx chain.**

`interval → flatMapSingle(read) → map(transform) → flatMapSingle(write)`.
No loop. No temporary variable. No try/catch around the write.
If the read or write fails, the error propagates naturally.

```shell
jbang CalibrationPipeline.java \
  tango://localhost:10000/sys/tg_test/1 double_scalar \
  tango://localhost:10000/sys/tg_test/1 double_scalar_w \
  2.0 10.0 1000
```

Arguments: `<src-device> <src-attr> <dst-device> <dst-attr> <gain> <offset> [interval-ms=1000]`  — Ctrl+C to stop.

Key code:
```java
Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    // Step 1: read source attribute
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(srcDevice, srcAttr))
                .firstOrError()
                .map(raw -> ((Number) raw).doubleValue())
    )
    // Step 2: apply linear calibration — pure function, no I/O
    .map(raw -> raw * gain + offset)
    // Step 3: write calibrated value; ignoreElements + andThen passes the value downstream
    .flatMapSingle(calibrated ->
        Flowable.fromPublisher(new RxTangoAttributeWrite<>(dstDevice, dstAttr, calibrated))
                .ignoreElements()
                .andThen(Single.just(calibrated))
    )
    .blockingSubscribe(
        v   -> System.out.printf("wrote %.6f → %s/%s%n", v, dstDevice, dstAttr),
        err -> System.err.println("ERROR: " + err.getMessage())
    );
```

---

## 8. The showstopper — fluent TangoClient pipeline

**Six steps. Six device interactions. Zero callbacks. Zero intermediate variables.**

`TangoClient` is a fluent builder over a `Single<Object>` chain.
Each method appends one step; `blockingGet()` drives the whole pipeline.
The result of every step is the input to the next.

```shell
jbang TangoTestPipeline.java \
  tango://localhost:10000/sys/tg_test/1
```

Output shows each step as it executes:

```
  [1] read    double_scalar  =  234.7612...
  [2] DevDouble returned     =  234.7612...
  [3] calibrated             =  471.0724...
  [4] DevString returned     =  calibrated=471.0724
  [5] wrote   string_scalar  =  calibrated=471.0724

  Pipeline complete.
  Confirmed on device: "calibrated=471.0724"
```

Key code:
```java
// Each method returns `this` — the chain grows step by step.
// executeCommand(device, cmd, v -> v) passes the previous result as the command input.
// writeAttribute(device, attr, v -> v) writes whatever the previous step produced.
// map() applies a pure function — no I/O, just transforms the value in the chain.
// blockingGet() subscribes and drives the entire pipeline to completion.
Object result = new TangoClient()

    // 1. read raw sensor value from the device
    .readAttribute(device, "double_scalar")
    .map(v -> { System.out.printf("  [1] read    double_scalar  =  %s%n", v); return v; })

    // 2. round-trip through DevDouble (proves the value physically left and returned)
    .executeCommand(device, "DevDouble", v -> v)
    .map(v -> { System.out.printf("  [2] DevDouble returned     =  %s%n", v); return v; })

    // 3. apply calibration locally — no device I/O here
    .map(v -> Math.abs(((Number) v).doubleValue()) * 2.0 + 1.5)
    .map(v -> { System.out.printf("  [3] calibrated             =  %s%n", v); return v; })

    // 4. format as string via DevString — cross-type step (double in, String out)
    .executeCommand(device, "DevString", v -> String.format("calibrated=%.4f", v))
    .map(v -> { System.out.printf("  [4] DevString returned     =  %s%n", v); return v; })

    // 5. persist result on the device (string_scalar holds its written value)
    .writeAttribute(device, "string_scalar", v -> v)
    .map(v -> { System.out.printf("  [5] wrote   string_scalar  =  %s%n", v); return v; })

    // 6. read back to confirm what the device actually has
    .readAttribute(device, "string_scalar")

    .blockingGet();
```

---

## 9. Throttle — rate control for fast producers

**The device updates faster than you need. `throttleLast` bridges the gap — one operator, no sleep, no counter.**

Poll at 50 ms (20 Hz) but only display at 1 s (1 Hz). The 95% of readings that
arrive between display ticks are silently dropped inside the Rx chain. The upstream
poll rate is unaffected — you still get the freshest possible value at each display tick.

```shell
jbang TangoTestThrottle.java \
  tango://localhost:10000/sys/tg_test/1 50 1000
```

Arguments: `<device> [poll-ms=50] [display-ms=1000]`  — Ctrl+C to stop.

Key code:
```java
Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
    // read at full poll rate — device sees every request
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                .firstOrError()
                .map(v -> ((Number) v).doubleValue())
    )
    .doOnNext(v -> polled.incrementAndGet())   // count every upstream value
    // throttleLast: of all values arriving within each displayMs window,
    // keep only the most recent one and discard the rest.
    // One operator replaces: synchronized flag, manual drop counter, sleep loop.
    .throttleLast(displayMs, TimeUnit.MILLISECONDS)
    .doOnNext(v -> displayed.incrementAndGet())
    .blockingSubscribe(
        v -> System.out.printf("  %+.6f   (polled %3d, displayed %3d)%n",
                v, polled.get(), displayed.get()),
        err -> System.err.println("ERROR: " + err.getMessage())
    );
```

---

## 10. Sliding average — noise reduction with `buffer`

**A rolling mean over the last N samples. No circular buffer, no index arithmetic — `buffer(N, 1)` does it all.**

`buffer(N, 1)` emits overlapping windows of N consecutive values, stepping forward
by 1 each tick. Each window is mapped to its mean. High-frequency noise averages out;
slow trends remain visible. The "noise" column shows how far each raw reading
deviates from its smoothed value.

```shell
jbang TangoTestSlidingAverage.java \
  tango://localhost:10000/sys/tg_test/1 5 400
```

Arguments: `<device> [window=5] [interval-ms=400]`  — output starts after the first full window.

Key code:
```java
Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                .firstOrError()
                .map(v -> ((Number) v).doubleValue())
    )
    // buffer(N, 1): emit a List<Double> of the last N values after every new sample.
    // window advances by 1 each tick:
    //   tick N:   [v1..vN]
    //   tick N+1: [v2..vN+1]
    // No output until the first N samples have accumulated.
    .buffer(window, 1)
    .map(buf -> {
        double sum = 0;
        for (double x : buf) sum += x;
        double raw      = buf.get(buf.size() - 1); // most recent sample
        double smoothed = sum / buf.size();
        return new double[]{ raw, smoothed };
    })
    .blockingSubscribe(
        pair -> System.out.printf("  %+16.6f  %+18.6f  %+.6f%n",
                pair[0], pair[1], pair[0] - pair[1]),
        err  -> System.err.println("ERROR: " + err.getMessage())
    );
```

---

## 11. Running statistics — live aggregation with `scan`

**Streaming min/max/mean/stddev that updates after every single sample. O(1) memory. No batch. No list.**

`scan()` is the streaming counterpart of `reduce()`. Where `reduce()` waits for
the stream to complete and emits one result, `scan()` emits the running accumulation
after every value — the statistics table updates live as data arrives.

Uses **Welford's online algorithm** for numerically stable variance: avoids the
catastrophic cancellation that naive `Σx² - n·mean²` suffers with large or
closely-spaced values.

Compare with `TangoTestStats`: that script collects N samples into a List, computes
once, and exits. This one runs indefinitely and never allocates a growing list.

```shell
jbang TangoTestRunningStats.java \
  tango://localhost:10000/sys/tg_test/1 500
```

Arguments: `<device> [interval-ms=500]`  — Ctrl+C to stop.

Key code:
```java
// Immutable accumulator; Stats::update implements Welford's algorithm.
record Stats(long n, double latest, double min, double max, double mean, double m2) {
    static Stats update(Stats s, double x) {
        long   n      = s.n + 1;
        double delta  = x - s.mean;
        double mean   = s.mean + delta / n;       // running mean, O(1)
        double delta2 = x - mean;
        double m2     = s.m2 + delta * delta2;    // Welford M2 accumulator
        return new Stats(n, x, Math.min(s.min, x), Math.max(s.max, x), mean, m2);
    }
    double stddev() { return n > 1 ? Math.sqrt(m2 / (n - 1)) : 0.0; }
}

Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                .firstOrError().map(v -> ((Number) v).doubleValue())
    )
    // scan() folds each value into the accumulator and emits a new Stats immediately.
    // Unlike reduce(), scan() never waits for the stream to complete.
    .scan(Stats.zero(), Stats::update)
    .filter(s -> s.n() > 0)  // skip the empty seed
    .blockingSubscribe(
        s   -> System.out.printf("  %5d  %+14.6f  %+14.6f  %+14.6f  %+14.6f  %14.6f%n",
                s.n(), s.latest(), s.mean(), s.min(), s.max(), s.stddev()),
        err -> System.err.println("ERROR: " + err.getMessage())
    );
```

---

## 12. Backpressure — fast producer, slow consumer

**What happens when the device produces data faster than you can process it? Backpressure is the answer.**

The producer polls TangoTest at 100 ms (10 Hz).
The consumer takes 600 ms per item — 6× slower.
Without a strategy, RxJava's internal buffer fills up and the stream crashes with
`MissingBackpressureException`. Three strategies handle it differently:

| Strategy | Behaviour |
|----------|-----------|
| `latest` | Keep only the newest unprocessed value; consumer always wakes to fresh data |
| `drop`   | Discard every value that arrives while the consumer is busy |
| `buffer` | Queue up to N values; crash when full — useful to *show* the problem |

Run with `latest` (default) and watch the skip counter climb while values stay fresh:

```shell
jbang TangoTestBackpressure.java \
  tango://localhost:10000/sys/tg_test/1 100 600
```

Swap strategy to see `drop` behaviour:

```shell
jbang TangoTestBackpressure.java \
  tango://localhost:10000/sys/tg_test/1 100 600 --strategy drop
```

Trigger the exception intentionally with a tiny buffer:

```shell
jbang TangoTestBackpressure.java \
  tango://localhost:10000/sys/tg_test/1 100 600 --strategy buffer --buffer-size 5
```

Key code:
```java
// Fast upstream: read Tango at 100 ms poll rate.
Flowable<Double> upstream = Flowable.interval(pollMs, TimeUnit.MILLISECONDS)
    .flatMapSingle(tick ->
        Flowable.fromPublisher(new RxTangoAttribute<>(device, "double_scalar"))
                .firstOrError().map(v -> ((Number) v).doubleValue())
    )
    .doOnNext(v -> produced.incrementAndGet());

// Apply backpressure strategy between producer and consumer.
//
// onBackpressureLatest — replaces the pending slot with the newest arrival.
//   Consumer always processes the most recent reading, never stale queued data.
//
// onBackpressureDrop — discards values arriving while the consumer is busy.
//   Even the newest arrival is dropped if no slot is free yet.
//
// onBackpressureBuffer(N) — queues up to N items, then throws
//   MissingBackpressureException. Use this to demonstrate the failure mode.
Flowable<Double> bounded = upstream.onBackpressureLatest();

// observeOn decouples producer and consumer onto separate threads.
// Without it both run on the same thread — no backpressure ever builds.
bounded
    .observeOn(Schedulers.single())
    .blockingSubscribe(
        v -> {
            long c = consumed.incrementAndGet();
            System.out.printf("  prod=%d  cons=%d  skipped=%d  value=%+.6f%n",
                    produced.get(), c, produced.get() - c, v);
            Thread.sleep(processMs); // simulate slow downstream work
        },
        err -> System.err.printf("ERROR (%s): %s%n",
                err.getClass().getSimpleName(), err.getMessage())
    );
```

---

## Bonus: Spec compliance verification

Verifies all RxJTango publishers against the
[reactive-streams TCK](https://github.com/reactive-streams/reactive-streams-jvm/tree/master/tck)
— the official compatibility test suite.

```shell
jbang VerifySpec.java
```

Expected: 12 tests pass, several skip (skips are correct — the TCK has tests
for publishers that emit 2+ items; `RxTangoAttribute` is single-shot by design).

---

## All catalog aliases

Run any example from the repo root without specifying the file path:

| Alias | Example |
|-------|---------|
| `jbang read-attribute@. <device> <attr>` | Read one or more attributes |
| `jbang poll@. <device> <attr> <ms>` | Continuous poll |
| `jbang snapshot@. <device> <attr> [...]` | Parallel multi-attribute snapshot |
| `jbang stats@. <device> [N] [ms]` | Collect N samples, print statistics |
| `jbang correlate@. <device> [ms]` | Correlated parallel reads |
| `jbang calibrate@. <src-dev> <src-attr> <dst-dev> <dst-attr> <gain> <offset> [ms]` | Read-transform-write |
| `jbang alarm@. <threshold> <ms> <device> <attr> [...]` | Fan-in alarm monitor |
| `jbang pipeline@. <device>` | Fluent 6-step pipeline |
| `jbang throttle@. <device> [poll-ms] [display-ms]` | Rate control with `throttleLast` |
| `jbang sliding-avg@. <device> [window] [ms]` | Rolling average with `buffer(N,1)` |
| `jbang running-stats@. <device> [ms]` | Live streaming stats with `scan` |
| `jbang backpressure@. <device> [poll-ms] [process-ms] [--strategy latest\|drop\|buffer]` | Fast producer vs slow consumer |
| `jbang verify-spec@.` | Run reactive-streams TCK |
