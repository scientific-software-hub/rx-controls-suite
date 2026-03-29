# rx-controls-suite

Reactive Programming Suite for Scientific Control Systems — the same
[ReactiveX](https://reactivex.io/) operator vocabulary across multiple control-system platforms.

```
poll → zip → sliding-average → backpressure → fluent pipeline
```

Works the same way whether you're talking to **Tango Controls** (Java) or **EPICS** (Python).

---

## Sub-projects

| Sub-project | Platform | Language | Stack |
|---|---|---|---|
| [RxTango/java](RxTango/java/) | Tango Controls | Java 11+ | jbang + RxJava3 + ezTangoAPI |
| [RxEpics/python](RxEpics/python/) | EPICS Channel Access | Python 3.10+ | uv + RxPY v4 + caproto |
| [RxTine/java](RxTine/java/) | TINE (DESY) | Java 11+ | jbang + RxJava3 + TINE Java API |

---

## RxTango/java — quick start

Prerequisites: [jbang](https://www.jbang.dev/), Docker, JTango artifacts in `~/.m2` (see [RxTango/java/README.md](RxTango/java/README.md)).

```shell
cd RxTango/java
docker compose up -d          # start Tango stack (MariaDB + DatabaseDS + TangoTest)

# run examples directly
jbang examples/ReadAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar
jbang examples/PollAttribute.java tango://localhost:10000/sys/tg_test/1 double_scalar 500

# or via catalog aliases
jbang stats@.     tango://localhost:10000/sys/tg_test/1
jbang pipeline@.  tango://localhost:10000/sys/tg_test/1
```

---

## RxEpics/python — quick start

Prerequisites: Python 3.10+, [uv](https://docs.astral.sh/uv/) or pip, Docker.

```shell
cd RxEpics/python
pip install -r requirements.txt
docker compose up -d          # start soft IOC with TEST:CALC, TEST:DOUBLE, ...

python examples/read_pv.py TEST:DOUBLE TEST:LONG
python examples/monitor_pv.py TEST:CALC
python examples/pv_pipeline.py
```

---

## Design philosophy

- **One vocabulary, many platforms.** `poll`, `zip`, `sliding average`, `backpressure`,
  `fluent pipeline` — the same patterns, regardless of the underlying control system.
- **Spec-compliant.** RxTango publishers are verified against the
  [reactive-streams TCK](https://github.com/reactive-streams/reactive-streams-jvm/tree/master/tck).
- **No framework lock-in.** Production code depends only on `org.reactivestreams` (Java)
  or `reactivex` (Python). RxJava3 / caproto are used in examples but swappable.
- **Zero build step for examples.** jbang inline deps for Java; plain `python` for Python.

---

## License

[AGPL-3.0](LICENSE) for open / non-commercial use.
Commercial use requires a separate license — see [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md).
