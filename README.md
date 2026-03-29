# RxJTango

Reactive Streams for Tango Controls — a spec-compliant implementation of
[reactive-streams-jvm](https://github.com/reactive-streams/reactive-streams-jvm)
on top of [ezTangoAPI](https://github.com/scientific-software-hub/JTango).

No Maven. No build step. Every example runs directly with [jbang](https://www.jbang.dev/).

---

## What is this?

Tango Controls gives you `DeviceProxy` — imperative, blocking, one-call-at-a-time.
RxJTango wraps it in `Publisher<T>` so you can compose device interactions the same
way you compose streams of data:

```
interval(500ms) → read double_scalar → ×2 + 1.5 → write double_scalar_w
```

becomes a single, readable chain instead of a loop with try/catch and manual threading.

The library itself depends only on `org.reactivestreams` interfaces.
Examples use RxJava3 (`Flowable`, `Single`) as the composition layer,
but any reactive-streams-compatible library works.

---

## Prerequisites

- [jbang](https://www.jbang.dev/) — `sdk install jbang` or `curl -Ls https://sh.jbang.dev | bash`
- Java 11+
- Docker (for the Tango stack)
- GitHub Packages access for JTango artifacts (see below)

### JTango artifacts — one-time setup

The Tango client library is hosted on GitHub Packages and requires a
[classic PAT](https://github.com/settings/tokens) with `read:packages` scope.

Add this to `~/.m2/settings.xml`:

```xml
<settings>
  <servers>
    <server>
      <id>jtango</id>
      <username>YOUR_GITHUB_USERNAME</username>
      <password>YOUR_CLASSIC_PAT</password>
    </server>
  </servers>
</settings>
```

The `id` must be `jtango` — it matches the `//REPOS` alias in every example script.

---

## Start the Tango stack

```shell
docker compose up -d
```

Three containers start: MariaDB → DatabaseDS (port 10000) → TangoTest (`sys/tg_test/1`).
Each waits for the previous to pass its health check before starting.

Wait about 10 seconds, then verify:

```shell
docker compose ps
```

---

## Quick demo

```shell
jbang examples/ReadAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar long_scalar
```

Or use the catalog aliases (run from the repo root):

```shell
jbang read-attribute@. tango://localhost:10000/sys/tg_test/1 double_scalar long_scalar
jbang stats@.          tango://localhost:10000/sys/tg_test/1
jbang pipeline@.       tango://localhost:10000/sys/tg_test/1
```

---

## Library architecture

```
org.tango.client.rx
├── RxTango<T>                       Abstract base — Publisher<T>, single-shot
│   ├── RxTangoAttribute<T>          Read one attribute
│   ├── RxTangoAttributeWrite<T>     Write one attribute (emits Void)
│   └── RxTangoCommand<T,V>          Execute one command (input V, result T)
├── RxTangoAttributeChangePublisher<T>  Push publisher for CHANGE/PERIODIC/ARCHIVE events
└── TangoClient                      Fluent builder — chains RxJava Singles
```

`RxTango` subclasses are **single-shot**: one item per subscription.
Combine with `Flowable.interval(...).flatMapSingle(...)` for continuous polling.

`RxTangoAttributeChangePublisher` is **multi-value / push**: lives as long as
the underlying Tango event subscription.

---

## Spec compliance

All publishers are verified against the
[reactive-streams TCK](https://github.com/reactive-streams/reactive-streams-jvm/tree/master/tck):

```shell
jbang examples/VerifySpec.java
```

12 applicable tests pass. Skips are expected for a single-shot publisher
(the TCK has tests for publishers that emit 2+ items; those are correctly skipped).

---

## Examples

See **[examples/README.md](examples/README.md)** for the full demo playbook —
ordered from the simplest read to the showstopper fluent pipeline,
with narrative explanations and exact jbang commands you can run directly
from IntelliJ IDEA.

---

## Project layout

```
src/          Library source (no jbang headers — included via //SOURCES)
examples/     Runnable jbang scripts + README.md playbook
docker-compose.yml   SKAO Tango stack (MariaDB + DatabaseDS + TangoTest)
jbang-catalog.json   Catalog aliases (read-attribute, stats, pipeline, ...)
```
