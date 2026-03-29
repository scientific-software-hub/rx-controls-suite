# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Build & Run

This project uses [jbang](https://www.jbang.dev/) — no Maven, no build step. Each example script is self-contained and runnable directly.

```bash
# Run an example directly
jbang examples/ReadAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar

# Or via the catalog aliases (from within the repo)
jbang read-attribute@. tango://localhost:10000/sys/tg_test/1 double_scalar
jbang monitor@.        tango://localhost:10000/sys/tg_test/1 State
jbang zip@.            tango://host1:10000/dev/sensor/1 temperature \
                        tango://host2:10000/dev/sensor/2 pressure 500
```

Dependencies are declared inline with `//DEPS` and fetched by jbang on first run (cached in `~/.jbang/`). The Tango-specific artifacts (`ezTangoAPI`, `TangORB`) must be present in the local Maven cache (`~/.m2/repository`) — they are not on Maven Central. If you previously built with Maven they will already be there.

## Project Layout

```
src/          Library source files (package org.tango.client.rx)
examples/     Runnable jbang demo scripts; each //SOURCES ../src/*.java
```

Source files have no jbang headers — they are plain Java used via `//SOURCES` by the example scripts. Only the scripts in `examples/` are entry points.

## Architecture

RxJTango wraps [ezTangoAPI](https://github.com/hzg-wpi/ez-tango-api) (`TangoProxy`) with [reactive-streams-jvm](https://github.com/reactive-streams/reactive-streams-jvm) `Publisher` interfaces.

**Class hierarchy:**

- `RxTango<T>` — abstract base; implements `Publisher<T>`; holds a `TangoProxy` + operation name; `subscribe()` executes `getFuture()` asynchronously, emits one item, then `onComplete`.
  - `RxTangoCommand<T,V>` — executes a Tango command (optional input `V`, result `T`).
  - `RxTangoAttribute<T>` — reads a Tango attribute.
  - `RxTangoAttributeWrite<T>` — writes a value to a Tango attribute; emits `Void` on success.
- `RxTangoAttributeChangePublisher<T>` — push publisher; subscribes to a Tango event (`CHANGE` by default, or `PERIODIC`/`ARCHIVE`) at construction time; implements both `Publisher<EventData<T>>` and `TangoEventListener<T>`; fans out events to all current subscribers. Cancelling removes the subscriber from the fan-out.

**Key design points:**
- `RxTango` subclasses are **single-shot** publishers (one item per subscription). Compose them with `Flowable.interval(...).flatMapSingle(...)` for polling.
- `RxTangoAttributeChangePublisher` is **push/multi-value** — it lives as long as the underlying Tango subscription.
- Production code depends only on `org.reactivestreams` interfaces. RxJava3 is used in examples but any reactive-streams-compatible library works.
- `RxTangoAttributeWrite` is write-only. To write-then-read, chain explicitly: `Flowable.fromPublisher(new RxTangoAttributeWrite<>(...)).ignoreElements().andThen(Flowable.fromPublisher(new RxTangoAttribute<>(...)))`.
