# rx-controls-suite

[![DOI](https://zenodo.org/badge/1195252803.svg)](https://doi.org/10.5281/zenodo.20614016)

Reactive Programming Suite for Scientific Control Systems — the same
[ReactiveX](https://reactivex.io/) operator vocabulary across multiple control-system platforms.

```
poll → zip → sliding-average → backpressure → fluent pipeline
```

Works the same way whether you're talking to **EPICS** (Python or C++), **Tango Controls** (Java, Python, or C++), or **TINE** (Java).

---

## The problem, in the room you already work in

Beam drops. Somewhere on the ring, current falls below the safe threshold. The shutter
has to close — not eventually, on the *next* transition — and it has to reopen the moment
beam recovers, without missing the recovery and without hammering the PV with a write on
every single poll tick.

Every control-room engineer has written this. It usually looks like a thread, a global,
and a comparison against the last-known value:

```python
# "imperative style" — manual polling loop + bookkeeping
_shutter_open = None            # last known state, so we don't rewrite the PV every tick
_stop = threading.Event()

def shutter_supervisor_loop():
    global _shutter_open
    while not _stop.is_set():
        try:
            current = controller.read_attribute("BeamCurrent").value
            ok = current >= MIN_BEAM_CURRENT

            if ok != _shutter_open:                 # manual "did it change?" check
                shutter_pv.put(1 if ok else 0)
                _shutter_open = ok
                print("Shutter OPENED" if ok else "Shutter CLOSED")
        except Exception as e:
            print(f"supervisor error: {e}", file=sys.stderr)

        time.sleep(1.0)                             # must match every other poller's rate

threading.Thread(target=shutter_supervisor_loop, daemon=True).start()
```

It works. It's also where the bugs live: the `_shutter_open` global, the thread lifecycle
nobody remembers to join on shutdown, and the fact that the moment a *second* piece of
logic — an interlock abort trigger, or "wait for healthy beam before starting the next
projection" — also needs `BeamCurrent`, you're choosing between opening a second
`DeviceProxy` and polling twice, or hand-rolling a callback list to fan the one poll out:
pub/sub from scratch, with its own thread-safety to get right.

This is the same logic, unmodified, from the
[combined storage-ring/beamline demo](demo/synchrotron-beamline/guarded_scan.py):

```python
# demo/synchrotron-beamline/guarded_scan.py
# `health` is a *shared* 1 Hz poll (see facility.py: ring_health()) — every consumer
# below subscribes to the same stream; there is no second poll to open.
supervisor_disp = health.pipe(
    ops.map(lambda h: h.current >= MIN_BEAM_CURRENT),   # -> bool: is the beam OK?
    ops.distinct_until_changed(),                       # only pass on state *changes*
    ops.flat_map(
        lambda ok: write_pv(PV_SHUTTER, 1 if ok else 0, ctx)
    ),
).subscribe(
    on_next=lambda v: print(
        f"  {'🔆 Shutter OPENED' if v else '🔒 Shutter CLOSED'}"
        f"  (beam {'OK' if v else 'lost — scan paused'})"
    ),
    on_error=lambda e: print(f"  supervisor error: {e}", file=sys.stderr),
    scheduler=scheduler,
)
```

Read it against the loop above, line for line: `map` computes `ok`, exactly like the
`current >= MIN_BEAM_CURRENT` line. `distinct_until_changed` *is* the
`if ok != _shutter_open` check — there's no `_shutter_open` global because the operator
carries that state for you. `flat_map(write_pv(...))` is the PV write. Nothing here is a
new concept; it's the loop everyone already writes, minus the bookkeeping.

And because `health` ([facility.py](demo/synchrotron-beamline/facility.py)) is `share()`d,
the abort-trigger and the per-projection health gate elsewhere in the same demo subscribe
to that identical stream — one poll, three consumers, no second `DeviceProxy`, no thread to
launch or join. That's the trade this whole suite is making: the syntax costs you a day to
get used to; the bookkeeping, thread lifecycles, and hand-rolled fan-out it removes cost you
every incident afterward.

**See it animated, marble-diagram style, next to the live dashboard:**
[docs/reactive-primer](docs/reactive-primer/index.html).

---

## About

Every scientific control system framework — EPICS, Tango, TINE, DOOCS — already produces the
same handful of interaction shapes: a value read on demand, a value pushed on change, a command
executed once, a value written and acknowledged. But each framework exposes them through its own
bespoke, imperative client API (`caproto.Context`, `DeviceProxy`, `TLink`), with its own callback
style, its own push-vs-poll idiom, its own way of composing "read this, then that, then average
the last five." None of that plumbing is portable — a control-room dashboard rewritten from EPICS
to Tango is rewritten from scratch, even though the *shape* of the logic (poll/monitor → smooth →
threshold → alarm) never changed.

`rx-controls-suite` wraps each framework's client API in a thin reactive-streams layer so that
shape becomes the reusable part. `read_pv` / `read_attribute`, `monitor_pv` / `monitor_attribute`,
`write_pv` / `write_attribute` all return the same kind of object — an RxPY `Observable`, an RxCpp
`observable<T>`, an RxJava `Publisher` — so `poll`, `zip`, `buffer_with_count` (sliding average),
`flat_map`/`flatMap`, and backpressure operators work identically regardless of which control
system, or which language, sits underneath. Swapping the underlying facility means swapping one
function; the pipeline built on top is untouched.

The suite exists to make that case concretely, across every combination the field actually uses:
EPICS in Python and C++; Tango in Java, Python, and C++; TINE in Java — plus combined demos
(a Tango storage ring feeding an EPICS beamline, orchestrated by a Bluesky `RunEngine`) that show
the same reactive pipeline surviving a real multi-facility, multi-framework scan. **EPICS is the
suite's primary growth area going forward** — Python and C++ are both already at conformance-test
maturity, and `RxEpics/java` is the next planned sub-project (see [Sub-projects](#sub-projects)).

---

## Sub-projects

| Sub-project | Platform | Language | Stack |
|---|---|---|---|
| [RxEpics/python](RxEpics/python/) | EPICS Channel Access | Python 3.10+ | uv + RxPY v4 + caproto |
| [RxEpics/cpp](RxEpics/cpp/) | EPICS (PVA) | C++17 | CMake + RxCpp + PVXS |
| *RxEpics/java* | EPICS | Java 11+ | *planned* |
| [RxTango/java](RxTango/java/) | Tango Controls | Java 11+ | jbang + RxJava3 + ezTangoAPI |
| [RxTango/python](RxTango/python/) | Tango Controls | Python 3.10+ | uv + RxPY v4 + PyTango |
| [RxTango/cpp](RxTango/cpp/) | Tango Controls | C++17 | CMake + RxCpp + cppTango |
| [RxTine/java](RxTine/java/) | TINE (DESY) | Java 11+ | jbang + RxJava3 + TINE Java API |
| [RxDectris/python](RxDectris/python/) | DECTRIS SIMPLON (detector) | Python 3.10+ | uv + RxPY v4 + httpx + pyzmq/CBOR |

---

## Design philosophy

- **One vocabulary, many platforms.** `poll`, `zip`, `sliding average`, `backpressure`,
  `fluent pipeline` — the same patterns, regardless of the underlying control system.
- **Spec-compliant.** RxEpics/cpp and RxTango/cpp each ship a `verify_contract` conformance test
  against the ReactiveX contract; RxTango/java publishers are verified against the
  [reactive-streams TCK](https://github.com/reactive-streams/reactive-streams-jvm/tree/master/tck).
- **No framework lock-in.** Production code depends only on `org.reactivestreams` (Java)
  or `reactivex` (Python). RxJava3 / caproto are used in examples but swappable.
- **Zero build step for examples.** jbang inline deps for Java; plain `python` for Python; CMake + FetchContent for C++ (RxCpp fetched automatically).

---

## Same vocabulary, different control systems

`buffer_with_count(N, 1)` turns a plain stream of readings into a sliding average — no circular
buffer, no index arithmetic, one operator. Here it's the same four-operator shape applied to an
EPICS PV and a Tango attribute — different frameworks underneath, identical pipeline on top:

```python
# RxEpics/python/examples/pv_sliding_average.py
rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_pv(pv_name, ctx)),
    ops.buffer_with_count(window, 1),
    ops.map(lambda buf: (buf[-1], sum(buf) / len(buf))),   # (raw, smoothed)
).subscribe(on_next=lambda pair: print(f"raw={pair[0]:+.6f}  avg={pair[1]:.6f}"))
```

```python
# RxTango/python/examples/sliding_average.py
rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
    ops.flat_map(lambda _: read_attribute(device, "double_scalar")),
    ops.buffer_with_count(count=window, skip=1),
    ops.map(lambda buf: (buf[-1], sum(buf) / len(buf))),   # (raw, smoothed)
).subscribe(on_next=lambda pair: print(f"raw={pair[0]:+.6f}  avg={pair[1]:.6f}"))
```

`read_pv` becomes `read_attribute` — that's the entire diff. Everything downstream of the read
(`buffer_with_count`, the mean, the subscription) is untouched.

EPICS also gets a **push-native** version for free, since `monitor_pv` wraps caproto's
subscription (not a poll loop) behind the exact same operator:

```cpp
// RxEpics/cpp/examples/pv_sliding_average.cpp
auto sub = rxepics::monitor_pv<double>(pv, ctx)
    .buffer(window_size, 1)
    .filter([window_size](const std::vector<double>& w) { return (int)w.size() == window_size; })
    .map([](const std::vector<double>& w) { return std::accumulate(w.begin(), w.end(), 0.0) / w.size(); })
    .subscribe([](double avg) { std::cout << "  avg: " << avg << "\n"; });
```

No `rx.interval`, no `flat_map` — the CA monitor callback *is* the source. `.buffer(N, 1)` doesn't
care whether upstream is a poll or a push; it composes identically either way.

The same fluent, cross-type read → calibrate → write → format → write → read-back pipeline, built
from `EpicsClient()` / `TangoClient()`, exists unmodified across the suite:
[EPICS/Python](RxEpics/python/examples/pv_pipeline.py),
[Tango/Python](RxTango/python/examples/pipeline.py),
[Tango/Java](RxTango/java/examples/TangoTestPipeline.java), and
[Tango/C++](RxTango/cpp/examples/pipeline.cpp) — no threads, no callbacks, no intermediate
variables in any of them.

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

## RxEpics/cpp — quick start

Prerequisites: C++17 compiler, CMake 3.18+, PVXS (`find_package(PVXS)` or `pkg-config pvxs`), Docker.

```shell
cd RxEpics/cpp
docker compose up -d          # reuses RxEpics/python softIoc (TEST:CALC, TEST:DOUBLE, ...)

export EPICS_PVA_ADDR_LIST=localhost
export EPICS_PVA_AUTO_ADDR_LIST=NO

cmake -S . -B build
cmake --build build

./build/examples/read_pv TEST:DOUBLE TEST:LONG
./build/examples/monitor_pv TEST:CALC
./build/examples/pv_pipeline

# verify ReactiveX contract (first EPICS reactive conformance test in the suite)
./build/tests/verify_contract
```

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

## RxTango/python — quick start

Prerequisites: Python 3.10+, [uv](https://docs.astral.sh/uv/), Docker.

```shell
cd RxTango/python
uv venv && uv pip install -e .
docker compose up -d          # start Tango stack (MariaDB + DatabaseDS + TangoTest)

python examples/read_attribute.py
python examples/poll_attribute.py tango://localhost:10000/sys/tg_test/1
python examples/pipeline.py       tango://localhost:10000/sys/tg_test/1

# run the unit tests (no live Tango needed)
uv pip install -e ".[dev]"
pytest -v
```

---

## RxTango/cpp — quick start

Prerequisites: C++17 compiler, CMake 3.18+, cppTango (`pkg-config tango`), Docker.

```shell
cd RxTango/cpp
docker compose up -d          # reuses RxTango/java Tango stack (TangoTest sys/tg_test/1)

cmake -S . -B build
cmake --build build

./build/examples/read_attribute sys/tg_test/1 double_scalar
./build/examples/monitor_attribute sys/tg_test/1 double_scalar
./build/examples/pipeline sys/tg_test/1

# verify ReactiveX contract (Rx-spec conformance test)
./build/tests/verify_contract
```

---

## RxTine/java — quick start

Prerequisites: jbang, Docker, TINE jars in `docker/` (see [RxTine/java/CLAUDE.md](RxTine/java/CLAUDE.md)).

```shell
cd RxTine/java
cp /path/to/tine.jar /path/to/jsineServer.jar docker/
docker compose up -d          # start jsineServer (JSINESRV in context TEST)

jbang read-property@. /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine
jbang poll@.          /TEST/JSINESRV/SINEDEV_0@jsinesrv Sine 500
jbang pipeline@.      /TEST/JSINESRV/SINEDEV_0@jsinesrv
```

---

## Combined demo — Storage Ring × Beamline

`demo/synchrotron-beamline/` fuses the two simulators into one experiment:
one Python process reads from the Tango storage ring **and** drives the EPICS tomography
beamline, demonstrating beam-loss recovery, orbit-quality flagging, vacuum-burst abort,
and backpressure in a single declarative reactive pipeline.

```shell
cd demo/synchrotron-beamline
docker compose up -d --build
python guarded_scan.py --ascii
# second terminal
python inject_fault.py beam_loss
```

See [`demo/synchrotron-beamline/README.md`](demo/synchrotron-beamline/README.md) and
[`docs/combined-demo-talk/`](docs/combined-demo-talk/) for the full walkthrough.

### Bluesky variant

[`demo/synchrotron-beamline/bluesky/`](demo/synchrotron-beamline/bluesky/) re-runs the same
guarded scan under a **Bluesky `RunEngine`** instead of a hand-rolled script — positioning the
suite as Bluesky's cross-control-system composition layer, since Bluesky/ophyd is EPICS-native and
the Tango storage ring would otherwise be invisible to it. A small bridge (`rx_bluesky.py`) adapts
Rx `Observable`s to Bluesky `Status`/`Signal`/document-stream protocols in four functions; the
suspenders, pause/abort logic, and HDF5 archiving from the non-Bluesky demo are unchanged.

### Prefect and n8n variants

[`demo/workflow-engines/`](demo/workflow-engines/) drives the same guarded scan from two
non-Bluesky orchestrators — data points outside the "scientific orchestrator" family.

**Prefect** gives a visible DAG (`prepare_beamline → run_sweep ×N → finalize`); a two-tier
beam-loss design lets ordinary dropouts stay invisible while a sustained one pauses the
flow run for an operator (auto-resuming the moment beam recovers), and a vacuum-burst
interlock ends the run **Failed** with the reason attached. Live feedback lands in the
Prefect UI via a bridge (`rx_prefect.py`) that documents a hard-won gotcha: Prefect's run
context is thread-local and doesn't cross into the rx event loop's own thread, so every
SDK call has to be marshalled back across that boundary.

**n8n** has no in-process Python step for this stack, so the scan is exposed as an
HTTP+SSE service (`scan_service.py`) and n8n's node graph is the orchestration. Two
findings the n8n half is built to surface: (1) with no shared process, the scan's live
state becomes a server-side session and n8n holds only control flow — the price and the
payoff of making an experiment a REST resource; (2) the n8n graph is a genuine **cycle**,
not a longer DAG — a quality-driven refinement loop re-acquires whatever projections a
full pass flagged LOW and re-assesses. It ships with its own instrument-panel dashboard
because per-node output is coarser than Prefect's live artifacts — a gap the demo states
rather than hides.

### Reactive Query Cache

[`demo/reactive-query-cache/`](demo/reactive-query-cache/) demonstrates an app-level cache built
from the suite's own Rx primitives — conceptually a TanStack-Query `QueryClient` for SCADA reads.
`read_attribute`/`read_pv` are cold, unicast Observables: N dashboard panels subscribing to the
same PV/attribute normally means N upstream reads. `QueryCache` coalesces same-key subscriptions
into one upstream read via `ReplaySubject` + ref-counting + a GC grace timer, so SCADA load stays
constant as the UI grows.

---

## RxDECTRIS integration demo

[`demo/dectris-integration/`](demo/dectris-integration/) puts a (simulated) **DECTRIS
detector** into the same reveal: a SIMPLON-shaped simulator (real Stream V2 wire format —
ZeroMQ + CBOR) plus a conceptual D.LAB-shaped processing mock, orchestrated by one
experiment recipe — `wait_until_healthy → acquire_series → correlate_with(facility) →
process_with(dlab)` — that runs unmodified against either facility adapter:

```shell
cd demo/dectris-integration
docker compose up -d --build
python experiment.py --facility tango --frames 100 --count-time 0.01
python experiment.py --facility epics --frames 100 --count-time 0.01
```

The only difference between the two runs is the `--facility` flag. Both facility adapters
observe the *same* simulated storage ring through different control systems (EPICS via a
small `facility_bridge.py` mirror, Tango directly), so the comparison is a fair one, not two
demos wearing the same recipe. `inject_fault.py` drives all four fault scenarios (beam loss,
interlock, detector error, D.LAB processing retry) from one command; `dashboard.py` renders
FACILITY / DETECTOR / D.LAB status live. See
[`demo/dectris-integration/README.md`](demo/dectris-integration/README.md) for the
architecture and what this demo does/doesn't claim, and
[`demo/dectris-integration/demo-script.md`](demo/dectris-integration/demo-script.md) for the
meeting-ready walkthrough. The reusable SIMPLON wrapper itself lives at
[`RxDectris/python`](RxDectris/python/).

---

## Talks

The suite started life as a Tango talk; EPICS Collaboration Meeting material is where the current
work is headed — see the [About](#about) section.

| Talk | Format | Link |
|---|---|---|
| EPICS (Python) | slides | [docs/epics-talk/](docs/epics-talk/) |
| RxEpics/cpp | slides | [docs/rxepics-cpp-talk/](docs/rxepics-cpp-talk/) |
| Combined demo (Storage Ring × Beamline) | slides | [docs/combined-demo-talk/](docs/combined-demo-talk/) |
| Prefect orchestration (managers & beamline scientists) | slides | [docs/prefect-talk/](docs/prefect-talk/) |
| Reactive Programming for Tango Controls (Tango Users Meeting) | recording | [YouTube](https://youtu.be/9CyGPIwJlxc) · [slides](docs/tango-talk/) |
| RxTango/python | slides | [docs/rxtango-python-talk/](docs/rxtango-python-talk/) |
| RxTango/cpp | slides | [docs/rxtango-cpp-talk/](docs/rxtango-cpp-talk/) |
| RxTine | slides | [docs/rxtine-talk/](docs/rxtine-talk/) |

All slide decks are also browsable from [docs/index.html](docs/index.html).

---

## License

[AGPL-3.0](LICENSE) for open / non-commercial use.
Commercial use requires a separate license — see [LICENSE-COMMERCIAL.md](LICENSE-COMMERCIAL.md).
