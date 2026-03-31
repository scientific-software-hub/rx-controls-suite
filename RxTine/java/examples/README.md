# RxTine/java — Live Demo Cookbook

Run examples from the `RxTine/java/` directory using the jbang catalog aliases.
The catalog bakes in `-Dtine.home=./client-config`, so no env var needed.

```shell
cd RxTine/java
docker compose up -d          # start jsineServer
docker compose ps             # wait until jsinesrv is healthy
```

All examples target `Context=TEST, Server=JSINESRV, Devices=SINEDEV_0…SINEDEV_9`.

---

## 0. TINE addressing primer

TINE addresses have the form `/CONTEXT/SERVER/DEVICE`.
There are no commands — write to a property instead.
`TDataType` always wraps an array; take index `[0]` for scalar properties.

```
/TEST/JSINESRV/SINEDEV_0
  │     │          └── device name
  │     └──────────── server (= exported equipment module)
  └────────────────── context
```

Two interaction modes are available — and they are architecturally different:

| Mode | Class | How it works |
|------|-------|--------------|
| Single-shot read | `RxTineRead` | Creates a `TLink`, calls `executeAndClose()`, destroys it. Client initiates. |
| Single-shot write | `RxTineWrite` | Same lifecycle; sets the property value, emits the written value. |
| Push monitor | `RxTineMonitor` | Creates one persistent `TLink`, calls `attach(CM_POLL, …)`. Server pushes updates at the requested rate. |

---

## 1. Read a property

**Problem:** I need the current value of a TINE property — once.

**Reactive solution:** `RxTineRead` is a `Publisher<T>` that emits exactly one value
and completes. `Flowable.fromPublisher()` bridges it into RxJava3's operator set.

```shell
jbang read-property@.. /TEST/JSINESRV/SINEDEV_0 Sine
```

Read `Sine` from multiple devices by running the command per device:

```shell
jbang read-property@.. /TEST/JSINESRV/SINEDEV_0 Sine
jbang read-property@.. /TEST/JSINESRV/SINEDEV_1 Sine
```

> **jsineServer property scope:** `Sine` is the only per-device property in this
> test server. `Amplitude`, `Frequency`, and `Noise` are module-level — they
> return `illegal device` (error 35) when requested with a named device like `SINEDEV_0`.

Key code:

```java
// RxTineRead.ofDouble() allocates a double[1] buffer and extracts buf[0].
// It is a cold Publisher: each subscription creates a fresh TLink.
Flowable.fromPublisher(RxTineRead.ofDouble(device, property))
    .blockingSubscribe(
        value -> System.out.printf("%s/%s = %.6f%n", device, property, value),
        err   -> System.err.printf("ERROR: %s%n", err.getMessage())
    );
```

---

## 2. Poll a property continuously

**Problem:** I need a live stream of values — read, pause, repeat.
A `while(true) + sleep` loop works but ties a thread, mixes timing with logic,
and has no composable error handling.

**Reactive solution:** `Flowable.interval()` is a metronome that emits ticks at a
fixed rate. `flatMapSingle` turns each tick into one read. The composition is
declarative: timing, I/O, and error handling are separate concerns.

```shell
jbang poll@.. /TEST/JSINESRV/SINEDEV_0 Sine 500
```

Key code:

```java
// interval() is the metronome — emits Long(0), Long(1), … every intervalMs.
// flatMapSingle fires one new TLink read per tick and collects its result.
// No loop. No thread management. No counter.
Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    .flatMapSingle(__ ->
        Flowable.fromPublisher(RxTineRead.ofDouble(device, property))
                .firstOrError()
    )
    .blockingSubscribe(
        v   -> System.out.printf("[%4d]  %+.6f%n", tick.incrementAndGet(), v),
        err -> System.err.println("ERROR: " + err.getMessage())
    );
```

**Note — poll vs monitor:** This example creates a new `TLink` on every tick
(client-initiated request/response). The server never holds state about this client.
Compare with example 3 (`monitor`) where one `TLink` lives for the whole session
and the server drives the updates.

---

## 3. Monitor — let the server push

**Problem:** I want the property stream driven by the server, not by my own timer.
Setting up a polling loop wastes round-trips; I want the server to notify me.

**Reactive solution:** `RxTineMonitor` calls `TLink.attach(CM_POLL, callback, intervalMs)`.
The server registers this client and sends updates at the requested rate over one
persistent connection. The client is a passive receiver — no repeated requests.

`RxTineMonitor` is a *hot* multi-subscriber `Publisher<T>`: it wraps a single
`TLink` and fans out each callback to all current subscribers.

```shell
jbang monitor@.. /TEST/JSINESRV/SINEDEV_0 Sine 500
```

Key code:

```java
// ofDouble() attaches the TLink immediately at construction time.
// The callback fires on TINE's internal thread pool.
RxTineMonitor<Double> monitor = RxTineMonitor.ofDouble(device, property, intervalMs);

Flowable.fromPublisher(monitor)
    .subscribe(
        v   -> System.out.printf("[%d]  %+.6f%n", System.currentTimeMillis(), v),
        err -> System.err.println("ERROR: " + err.getMessage())
    );

// close() detaches the TLink and completes all subscribers.
Runtime.getRuntime().addShutdownHook(new Thread(monitor::close));
Thread.currentThread().join();   // keep main thread alive until Ctrl+C
```

**poll vs monitor — when to use which:**

| | `poll` (RxTineRead + interval) | `monitor` (RxTineMonitor) |
|---|---|---|
| TLink lifetime | One per tick, created and destroyed | Single, lives until `close()` |
| Who drives timing | Client (jbang interval) | Server (CM_POLL) |
| Good for | Composing with other Rx operators | Efficient continuous stream |
| Multiple subscribers | Natural (each has its own TLink) | Fan-out from one TLink |

---

## 4. Calibration pipeline — read → transform → write

**Problem:** I need to continuously read a raw sensor value, apply a linear
calibration, and write the result to another property. With plain code this is a
`while(true)` loop with two try/catch blocks, a temp variable, and interleaved
logic and timing.

**Reactive solution:** Express the entire operation as a single Rx chain:

```
interval → flatMapSingle(read) → map(calibrate) → flatMapSingle(write)
```

Each step is a named transformation. Error handling is uniform across all three
I/O operations. There are no temporary variables, no nested try/catch, no loop.

```shell
jbang calibrate@.. \
    /TEST/JSINESRV/SINEDEV_0 Sine \
    /TEST/JSINESRV/SINEDEV_0 Amplitude \
    2.0 0.0 1000
```

Arguments: `<src-device> <src-property> <dst-device> <dst-property> <gain> <offset> [interval-ms=1000]`

> **jsineServer limitation:** `Amplitude` is module-level in the test server and
> returns `illegal device` when written with a named device. The pipeline pattern
> is valid — substitute a real per-device writable property from your TINE server.

Key code:

```java
Flowable.interval(intervalMs, TimeUnit.MILLISECONDS)
    // Step 1: read the source property
    .flatMapSingle(__ ->
        Flowable.fromPublisher(RxTineRead.ofDouble(srcDevice, srcProp))
                .firstOrError()
    )
    // Step 2: calibrate — pure function, zero I/O, zero side effects
    .map(raw -> raw * gain + offset)
    // Step 3: write the calibrated value; RxTineWrite emits the written value
    // so it flows naturally to the next step or to the subscriber
    .flatMapSingle(calibrated ->
        Flowable.fromPublisher(RxTineWrite.ofDouble(dstDevice, dstProp, calibrated))
                .firstOrError()
    )
    .blockingSubscribe(
        v   -> System.out.printf("[%d]  wrote %.6f → %s/%s%n",
                System.currentTimeMillis(), v, dstDevice, dstProp),
        err -> System.err.println("ERROR: " + err.getMessage())
    );
```

**Why `flatMapSingle` and not `map` for I/O?**
`map` is for synchronous pure functions. `flatMapSingle` is for operations that
are asynchronous or can fail (I/O, network). It subscribes to the inner Single,
waits for it to complete, and forwards either its value or its error — giving
you full back-pressure and error propagation for free.

---

## 5. Fluent TineClient pipeline

**Problem:** I need a multi-step workflow: read a value, derive a new setpoint,
write it back, and confirm by reading again. With raw API calls this produces a
chain of nested callbacks or a flat sequence of statements with no apparent
structure.

**Reactive solution:** `TineClient` is a fluent builder over a `Single<Object>`
chain. Each method appends one step; `blockingGet()` drives the whole pipeline.
The result of every step is the implicit input to the next.

```shell
jbang pipeline@.. /TEST/JSINESRV/SINEDEV_0
```

> **jsineServer limitation:** `Amplitude` is module-level in the test server; the
> write step (step 3) will return `illegal device`. Steps 1–2 execute correctly
> and demonstrate the read → transform part of the chain. Substitute a real
> per-device writable property to see the full pipeline succeed.

Key code:

```java
// Each method returns `this` — the chain grows step by step.
// read() and write() both use RxTineRead / RxTineWrite internally.
// map() applies a pure function with no device I/O.
// blockingGet() subscribes and drives the whole pipeline.
Object result = new TineClient()

    // 1. read raw sensor value
    .read(device, "Sine")
    .map(v -> { System.out.printf("  [1] read    Sine       =  %s%n", v); return v; })

    // 2. derive new amplitude locally — absolute value scaled up
    .map(v -> Math.abs(((Number) v).doubleValue()) * 2.0 + 1.5)
    .map(v -> { System.out.printf("  [2] new Amplitude      =  %s%n", v); return v; })

    // 3. write the derived value back to the device
    .write(device, "Amplitude")
    .map(v -> { System.out.printf("  [3] wrote  Amplitude   =  %s%n", v); return v; })

    // 4. read back to confirm what the device actually stored
    .read(device, "Amplitude")

    .blockingGet();
```

**No commands:** TINE has no command mechanism. If you need to trigger an action,
write to a dedicated property. The `TineClient` API has no `executeCommand()` for
this reason — the `read → transform → write` idiom replaces it entirely.

---

## All catalog aliases

Run any example from `RxTine/java/` — `-Dtine.home=./client-config` is baked in:

| Alias | File | Arguments |
|-------|------|-----------|
| `jbang read-property@. <device> <property> [...]` | ReadProperty.java | One or more properties |
| `jbang poll@. <device> <property> [interval-ms=500]` | PollProperty.java | Ctrl+C to stop |
| `jbang monitor@. <device> <property> [interval-ms=500]` | MonitorProperty.java | Ctrl+C to stop |
| `jbang calibrate@. <src-dev> <src-prop> <dst-dev> <dst-prop> <gain> <offset> [ms=1000]` | CalibrationPipeline.java | Ctrl+C to stop |
| `jbang pipeline@. <device>` | TineClientPipeline.java | Runs once and exits |
