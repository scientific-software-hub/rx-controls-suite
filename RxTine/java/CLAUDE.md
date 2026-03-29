# RxTine/java — Claude Code Guide

Reactive Streams for TINE (Three-fold Integrated Networking Environment).
Java implementation using jbang + RxJava3 + TINE Java client API.

## Build & Run

No Maven. No build step. Each example is a self-contained jbang script.

```bash
jbang examples/ReadProperty.java /HERA/Context/Device SENSOR
jbang read-property@.            /HERA/Context/Device SENSOR STATUS
jbang poll@.                     /HERA/Context/Device SENSOR 500
jbang monitor@.                  /HERA/Context/Device SENSOR 500
jbang calibrate@.  /HERA/Context/DevA SENSOR /HERA/Context/DevB SETPOINT 2.0 10.0 1000
jbang pipeline@.   /HERA/Context/Device
```

## Prerequisites

- [jbang](https://www.jbang.dev/) — `sdk install jbang`
- Java 11+
- TINE Java jar installed in `~/.m2` — not on Maven Central.
  Download from https://tine.desy.de and install manually:
  ```bash
  mvn install:install-file -Dfile=tine-4.4.jar \
      -DgroupId=de.desy.tine -DartifactId=tine -Dversion=4.4 -Dpackaging=jar
  ```
  Adjust the version to whatever you downloaded.

## Project layout

```
src/          Library source (no jbang headers — included via //SOURCES)
examples/     Runnable jbang demo scripts
```

## Architecture

TINE access uses a three-part address: `devName` (e.g. `/HERA/Context/Device`)
and `property` (e.g. `SENSOR`). The central class is `TLink`.

**Class hierarchy:**

- `RxTine<T>` — abstract base; implements `Publisher<T>`.
  Manages the reactive-streams subscription contract (§1.1, §1.3, §1.7, §3.9).
  Subclasses implement `execute(Subscriber)` with the actual TLink operation.
  - `RxTineRead<T>` — single-shot read via `TLink.executeAndClose()`.
    Factory methods: `ofDouble`, `ofInt`, `ofString`, `ofDoubleArray`.
  - `RxTineWrite<T>` — single-shot write via `TLink.execute()` with `CA_WRITE`.
    Emits the written value on success so it can flow into the next pipeline step.
- `RxTineMonitor<T>` — push publisher; wraps `TLink.attach(CM_POLL, callback, intervalMs)`.
  Keeps a single TLink alive; fans out callbacks to all active subscribers.
  Call `close()` to detach the TLink and complete all subscribers.
- `TineClient` — fluent builder over a `Single<Object>` chain, mirrors TangoClient.
  Methods: `read`, `write` (pass-through / static / fn-from-prev), `map`.
  No `executeCommand` — TINE has no commands; write to a property instead.

**Key design points:**

- `RxTineRead` and `RxTineWrite` are **single-shot** — one item per subscription.
  Compose with `Flowable.interval(...).flatMapSingle(...)` for continuous polling.
- `RxTineMonitor` is **push/multi-value** — lives as long as the TLink is attached.
- `TDataType` always returns arrays; use index `[0]` for scalar properties.
- Error check: `tlink.getLinkStatus() != 0` → `tlink.getLastError()` for message.
- Production code depends only on `org.reactivestreams`. RxJava3 is in examples only.
