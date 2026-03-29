# RxTine/java — Claude Code Guide

Reactive Streams for TINE (Three-fold Integrated Networking Environment).
Java implementation using jbang + RxJava3 + TINE Java client API.

## Build & Run

No Maven. No build step. Each example is a self-contained jbang script.

```bash
# start the local test server first (see Docker section below)
docker compose up -d

# then run examples against the test device
jbang read-property@. /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine
jbang poll@.          /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine 500
jbang monitor@.       /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine 500
jbang calibrate@.     /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine \
                      /TEST/JSINESRV/SINEDEV_0@jsinesrv Amplitude 2.0 0.0 1000
jbang pipeline@.      /TEST/JSINESRV/SINEDEV_0@jsinesrv
```

## Prerequisites

- [jbang](https://www.jbang.dev/) — `sdk install jbang`
- Java 11+
- Docker + Docker Compose — for the local test server
- TINE Java jar installed in `~/.m2` — not on Maven Central.
  Download from https://tine.desy.de and install manually:
  ```bash
  mvn install:install-file -Dfile=tine-4.4.jar \
      -DgroupId=de.desy.tine -DartifactId=tine -Dversion=4.4 -Dpackaging=jar
  ```
  Adjust the version to whatever you downloaded.

## Docker — local test server

The official `jsineServer` from the TINE distribution — analogous to `TangoTest`
and the EPICS soft IOC. Exports a propagating sine wave on 10 devices.

```bash
# 1. copy the TINE jars into docker/ (not committed to git)
cp /path/to/tine.jar docker/
cp /path/to/jsineServer.jar docker/

# 2. build and start
docker compose up -d

# 3. verify — should print the Sine value
jbang read-property@. /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine
```

### Test device address

```
/TEST/JSINESRV/SINEDEV_0@jsinesrv
 │     │          │          └── direct host — bypasses TNS (name service)
 │     │          └──────────── device name  (from SJNEQM-devices.csv)
 │     └─────────────────────── server name  (from fecid.csv)
 └───────────────────────────── context      (from fecid.csv)
```

### Exported properties

| Property    | Type    | Access | Description                              |
|-------------|---------|--------|------------------------------------------|
| `Sine`      | float[] | R      | Propagating sine wave value (per device) |
| `Amplitude` | float   | R/W    | Amplitude of the sine wave               |
| `Frequency` | float   | R/W    | Frequency of the sine wave               |
| `Noise`     | float   | R      | Noise level added to the sine wave       |

### Config files

All under `docker/` — override without rebuilding by mounting `docker/config/`:

| File                 | Purpose                                          |
|----------------------|--------------------------------------------------|
| `fecid.csv`          | FEC name + context (`JSINESRV, TEST`)            |
| `exports.csv`        | Property reference (server registers in code)    |
| `SJNEQM-devices.csv` | Device list (`SINEDEV_0` … `SINEDEV_9`)          |
| `tine.properties`    | Port, TNS settings, log level                    |

## Project layout

```
src/          Library source (no jbang headers — included via //SOURCES)
examples/     Runnable jbang demo scripts
docker/       Test server source, config files, Dockerfile
docker-compose.yml
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
