# Poll-operator audit

Every site in the repo where a *repeating* source (`rx.interval`/`Flowable.interval`/
`rxcpp::observable<>::interval`, or a hot upstream) feeds a per-tick I/O operation through a
merge-style flatten (`flat_map`/`flatMapSingle`/`flat_map`), classified and — for FIX rows —
corrected.

Categories: **FIX** (unbounded merge on a poll-shaped site, corrected below) · **REVIEW**
(intentional fast producer — the demo's whole point; left as `flat_map` with a comment) ·
**JUDGMENT** (write-side supervisor ordering; corrected per human decision) · **DO NOT TOUCH**
(fan-out concurrency or a single-item sequential chain — `flat_map` is not a poll here).

## Operator vocabulary used below

RxPY has no `exhaust_map`; the exhaust idiom is `ops.map(read) + ops.exclusive()` (verified
against installed `reactivex` 4.1.0/5.1.0 — see `CHANGES.md`). RxJava 3.1.8 has no `exhaustMap`
either; the repo's own coalesce precedent (`examples/XRayScan.java:134,149`) is
`onBackpressureLatest().concatMapSingle(...)`. RxCpp gets `concat_map` only in this pass —
display-class C++ rows are marked `// TODO(coalesce):` since no cppTango/PVXS/cmake toolchain
is available here to validate a hand-rolled exhaust helper.

---

## Python — FIX (repeating source → per-tick read)

| File:line | Source | Inner | → Operator | Rationale |
|---|---|---|---|---|
| `RxEpics/python/examples/poll_pv.py:47` | interval | `read_pv` | `map`+`exclusive` | pure display poll |
| `RxEpics/python/examples/alarm_monitor.py:56` | interval×N→merge | `read_pv` | `concat_map` | alarm edges must not be missed |
| `RxEpics/python/examples/calibration_pipeline.py:55` | interval | `read_pv` | `map`+`exclusive` | display-class calibration loop |
| `RxEpics/python/examples/pv_running_stats.py:92` | interval | `read_pv` | `concat_map` | running stats — no sample may drop |
| `RxEpics/python/examples/pv_sliding_average.py:59` | interval | `read_pv` | `concat_map` | sliding window — no sample may drop |
| `RxEpics/python/examples/pv_stats.py:74` | interval+take(n) | `read_pv` | `concat_map` | fixed-N stats sample |
| `RxEpics/python/examples/pv_throttle.py:65` | interval | `read_pv` | `concat_map` | docstring commits to "IOC sees every request" — the demo's coalescing is `sample()` downstream, not the read step |
| `RxEpics/python/examples/pv_correlate.py:51` | interval | `zip(read,read)` | `concat_map` | feeds a printed diff; see Task D for correlate_snapshot |
| `RxEpics/python/examples/zip_pvs.py:57` | interval | `zip(read,read)` | `concat_map` | see Task D |
| `RxEpics/python/examples/multi_pv_snapshot.py:95` | interval | `snapshot()` (inner fan-out) | `map`+`exclusive` (outer only) | outer poll coalesces; inner fan-out stays `flat_map` |
| `RxEpics/python/demo/tomography/tomography_scan.py:58` | interval (`poll_until`) | `read_pv` | `map`+`exclusive` | wait-for-state poll, freshest matters |
| `RxTango/python/examples/poll_attribute.py:41` | interval | `read_attribute` | `map`+`exclusive` | pure display poll |
| `RxTango/python/examples/alarm_monitor.py:46` | interval×N→merge | `read_attribute` | `concat_map` | alarm edges must not be missed |
| `RxTango/python/examples/running_stats.py:51` | interval | `read_attribute` | `concat_map` | running stats window |
| `RxTango/python/examples/sliding_average.py:46` | interval | `read_attribute` | `concat_map` | sliding window |
| `RxTango/python/examples/stats.py:42` | interval | `read_attribute` | `concat_map` | fixed-N stats sample |
| `RxTango/python/examples/throttle.py:46` | interval | `read_attribute` | `concat_map` | same reasoning as the EPICS throttle demo — coalescing is `sample()` downstream |
| `RxTango/python/examples/zip_window.py:43` | interval | `read_attribute` | `concat_map` | window buffer — no sample may drop |
| `RxTango/python/examples/correlate.py:41` | interval | `zip(2 reads)`+catch | `concat_map` | see Task D |
| `RxTango/python/examples/zip_attributes.py:36` | single-shot (not a poll) | `zip(2 reads)` | *(unchanged)* | DO NOT TOUCH — one-shot snapshot |
| `RxTango/python/examples/retry.py:62` | interval | `read_attribute().pipe(retry(3))` | `concat_map` | retries must not overlap |
| `RxDectris/python/src/rxdectris/status.py:49` | interval | `read_status("state")` | `concat_map` | **library code** — feeds `distinct_until_changed`; a state transition must not be dropped. Docstring at L43 updated with the residual sub-tick blind spot |
| `demo/synchrotron-beamline/facility.py:113` (`ring_health`) | interval | `zip` of 3 reads (shared, `share()`d) | `concat_map` | **corrected from an initial `map`+`exclusive` filing**: this shared stream also feeds `guarded_scan.py`'s interlock abort trigger, which watches `interlocks` for an edge — coalescing could drop the one tick that caught it |
| `demo/synchrotron-beamline/facility.py:137` (`poll_until`) | interval | `read_pv` | `map`+`exclusive` | wait-for-condition poll |
| `demo/synchrotron-beamline/live_dashboard.py:253` | interval | `zip` of 46 reads | `map`+`exclusive` | pure display, heaviest tick — coalescing here matters most |
| `demo/synchrotron-beamline/bluesky/live_strip.py:139` | interval | `zip` of 7 reads | `concat_map` | **corrected from an initial `map`+`exclusive` filing**: `ingest()` tracks discrete events (each `cur_proj` advance, the ABORTED transition) into `events_total`/`aborted_at` — a coalescing poll could drop the tick that caught one |
| ~~`demo/synchrotron-beamline/guarded_scan.py:141,145,147,151,162,182,228-230`~~ | *(correction: these are steps inside `guarded_acquire_projection`'s one-shot per-projection pipeline — source is `write_pv(...)`, a single-item observable invoked once per projection, not a repeating `rx.interval`)* | | *(unchanged)* | **DO NOT TOUCH** — sequential single-shot chain; the only real poll here is inside `poll_until`'s own definition (`facility.py`, already fixed) |
| `demo/reactive-query-cache/query_cache.py:40` | *(docstring example only)* | `read_attribute` | `map`+`exclusive` | cache upstream is a display-class poll; docstring updated to match |
| `demo/reactive-query-cache/querycache_dashboard.py:119,125` | interval | `read_attribute`/`read_pv` | `map`+`exclusive` | dashboard poll |
| `demo/dectris-integration/facilities.py:141` | interval | `zip` of 3 `read_pv` | `concat_map` | **corrected from an initial `map`+`exclusive` filing**: `EpicsFacility.health()` plays the same interlock-gating role as `TangoFacility`'s `ring_health` — `wait_until_healthy`/`abort_on` watch `interlock_ok` for an edge |
| `demo/workflow-engines/scan_service.py:358` | `rx.timer` | `zip` of 4 reads + catch | `map`+`exclusive` | dashboard `/events` feed |
| `examples/tango_epics_normalize.py:67` | interval | `read_attribute` | `map`+`exclusive` | Demo A/B display poll |
| `examples/tango_epics_normalize.py:133` | interval | `zip` (Tango+EPICS) | `concat_map` | see Task D |

## Python — FIX (repeating/hot source → per-event write) — JUDGMENT rows, resolved

| File:line | Source | Inner | → Operator | Rationale |
|---|---|---|---|---|
| `demo/synchrotron-beamline/guarded_scan.py:403-409` | `health` (hot poll) + `distinct_until_changed` | `write_pv` (shutter) | `concat_map` | two rapid transitions must not race two writes into the wrong terminal state |
| `demo/workflow-engines/scan_core.py:104-119` | `health` (hot poll) + `distinct_until_changed` | `write_pv` (shutter) | `concat_map` | same hazard |
| `demo/dectris-integration/facility_bridge.py:47-56` | `ring_health` (2 Hz hot poll) | `zip` of 4 `write_pv` (facility mirror) | `concat_map` | **corrected from the brief's "DO NOT TOUCH/correct merge" filing** — this is the identical unordered-write hazard, not a parallel fan-out; a `write_pv` here is a mutation, not an independent read |
| `RxEpics/python/examples/calibration_pipeline.py:59` | downstream of interval chain | `write_pv` | `concat_map` | write must not race the next tick's write |
| ~~`RxTango/python/examples/calibration_pipeline.py:43,51`~~ | *(correction: this file has no `rx.interval` — it runs the pipeline once per invocation, not per tick)* | | *(unchanged)* | **DO NOT TOUCH** — sequential single-shot chain, not a poll |
| `examples/tango_epics_normalize.py:148` | downstream of interval chain | `write_pv` | `concat_map` | same |
| `demo/synchrotron-beamline/bluesky/guarded_scan_bluesky.py:216` | Bluesky `docs` (hot Subject) | `write_pv`/`zip` of writes | `concat_map` | document stream must write in order |

## Python — REVIEW (intentional fast producer — left unchanged, commented)

| File:line | Why it stays `flat_map` |
|---|---|
| `RxEpics/python/examples/pv_backpressure.py:88` | the demo's entire subject is what an unbounded merge does under a fast producer; coalescing would delete the point |
| `RxTango/python/examples/backpressure.py:49` | same |

Each gets: `# REVIEW: kept as flat_map — this demo exists to show unbounded-merge backpressure.`

## Python — DO NOT TOUCH (concurrency intended, or single-item upstream)

Fan-out snapshots (`from_iterable` source, not a repeating tick):
`RxEpics/python/examples/multi_pv_snapshot.py:40` (inner), `RxTango/python/examples/multi_device_snapshot.py:45`,
`RxTango/python/examples/zip_attributes.py:36`.

Sequential single-item chains (source is a single-item observable — `flat_map` here means
"andThen", not "poll"): every `*/client.py` fluent builder, `RxEpics/python/src/rxepics/retry.py:45`,
`RxEpics/python/examples/pv_pipeline.py`, `RxTango/python/examples/{fluent_client,pipeline,retry}.py`,
`RxEpics/python/demo/tomography/tomography_scan.py`'s write chain,
`demo/synchrotron-beamline/guarded_scan.py`'s per-projection write chain,
`demo/workflow-engines/scan_core.py`'s write chain, `demo/synchrotron-beamline/bluesky/devices.py`.

Retry internals: `RxEpics/python/src/rxepics/retry.py:45` and the retry examples above it in the
chain. Already correct: `demo/dectris-integration/recipes.py` (`concat_map` with its own written
rationale at ~L107). `demo/dectris-integration/facility_bridge.py`'s per-frame correlate step
(inside `recipes.py::correlate_with`) already uses `concat_map`.
`demo/synchrotron-beamline/bluesky/guarded_scan_bluesky.py:216` is **not** DO NOT TOUCH — see the
JUDGMENT row above; it converts to `concat_map`.

---

## C++ — FIX (`interval → flat_map(read)` → `concat_map`)

`concat_map` swap only, per the C++ decision — no coalescing helper (uncompilable here; recorded
as `// TODO(coalesce):` on the display-class rows).

| File:line | → Operator | Note |
|---|---|---|
| `RxEpics/cpp/examples/poll_pv.cpp:33` | `concat_map` | `// TODO(coalesce):` display poll |
| `RxEpics/cpp/examples/pv_stats.cpp:38` | `concat_map` | window sample — no drop |
| `RxEpics/cpp/examples/pv_correlate.cpp:39` | `concat_map` | see Task D note |
| `RxEpics/cpp/examples/calibration_pipeline.cpp:36` | `concat_map` | (the write at L40 stays a sequential chain step) |
| `RxTango/cpp/examples/poll_attribute.cpp:39` | `concat_map` | `// TODO(coalesce):` display poll |
| `RxTango/cpp/examples/running_stats.cpp:52` | `concat_map` | window sample |
| `RxTango/cpp/examples/stats.cpp:37` | `concat_map` | fixed-N sample |
| `RxTango/cpp/examples/sliding_average.cpp:39` | `concat_map` | window sample |
| `RxTango/cpp/examples/throttle.cpp:35` | `concat_map` | docstring commits to reading at full poll rate — coalescing is `sample_with_time()` downstream, not the read step |
| `RxTango/cpp/examples/correlate.cpp:39` | `concat_map` | see Task D note |
| `RxTango/cpp/examples/zip_attributes.cpp:40` | `concat_map` | see Task D note |
| `RxTango/cpp/examples/zip_window.cpp:40,46` | `concat_map` | window buffer, both interval sources |
| `RxTango/cpp/examples/retry.cpp:40,56` (both branches) | `concat_map` | retries must not overlap between ticks — **corrected**: the ":57 inner retry unchanged" filing was wrong, that line's outer flatten is fed directly by the same `interval`, only the `.retry()` call *inside* it is DO NOT TOUCH |
| `RxTango/cpp/examples/alarm_monitor.cpp:44` | `concat_map` | alarm edges must not be missed |
| `RxTango/cpp/examples/calibration_pipeline.cpp:37` | `concat_map` | (write at :41 unchanged, sequential step) |

## C++ — REVIEW

`RxEpics/cpp/examples/pv_backpressure.cpp` and `RxTango/cpp/examples/backpressure.cpp` (the whole
`RxTango/cpp/examples/backpressure.cpp:44` site) stay `flat_map` — same reasoning as Python.

## C++ — DO NOT TOUCH

`iterate(streams) → flat_map(identity)` fan-in merges: `RxTango/cpp/examples/alarm_monitor.cpp:58`,
`RxEpics/cpp/examples/alarm_monitor.cpp:44`, `RxEpics/cpp/examples/resilient_monitor.cpp:77`
(hot monitor streams — concurrency is correct). Fan-out snapshots:
`RxEpics/cpp/examples/multi_pv_snapshot.cpp:35`, `RxTango/cpp/examples/multi_device_snapshot.cpp:41`.
Sequential chains: `*/include/*/client.hpp`.

---

## Java — FIX (`interval → flatMapSingle(read)` → `concatMapSingle`, display rows also get `onBackpressureLatest()`)

| File:line | → Operator | Rationale |
|---|---|---|
| `RxTango/java/examples/PollAttribute.java:40` | `onBackpressureLatest().concatMapSingle` | pure display poll |
| `RxTango/java/examples/TangoTestStats.java:46` | `concatMapSingle` | fixed-N stats sample |
| `RxTango/java/examples/TangoTestThrottle.java:51` | `concatMapSingle` | comment commits to reading at full poll rate — coalescing is `throttleLast()` downstream, not the read step |
| `RxTango/java/examples/TangoTestSlidingAverage.java:55` | `concatMapSingle` | sliding window |
| `RxTango/java/examples/TangoTestRunningStats.java:80` | `concatMapSingle` | running stats window |
| `RxTango/java/examples/TangoTestBackpressure.java:79` | *(unchanged)* | REVIEW — the demo's subject |
| `RxTango/java/examples/TangoTestRetry.java:121` | `concatMapSingle` | retries must not overlap |
| `RxTango/java/examples/TangoTestCorrelate.java:45` | `concatMapSingle` | see Task D note |
| `RxTango/java/examples/ZipAttributes.java:53` | `concatMapSingle` | see Task D note |
| `RxTango/java/examples/TangoTestZipWindow.java:101,133,137,173,177` | *(unchanged)* | DO NOT TOUCH — already demonstrates the zip/combineLatest/buffer tradeoffs deliberately |
| `RxTango/java/examples/CalibrationPipeline.java:57` | `concatMapSingle` | write at :65 stays sequential |
| `RxTango/java/examples/AlarmMonitor.java:66` | `concatMapSingle` | alarm edges must not be missed |
| `RxTango/java/examples/MultiDeviceSnapshot.java:88` | `onBackpressureLatest().concatMapSingle` | display poll of a pre-built fan-out snapshot; inner fan-out at :68 stays `flatMapSingle` |
| `RxTango/java/examples/BeamLossScenario.java:188` | `concatMapSingle` (no `onBackpressureLatest` — the source is `Observable`, which has no backpressure protocol) | **corrected from an initial display-class filing**: this demo's whole point is alarm propagation on a state transition (its own docstring: "Demonstrates reactive alarm handling") — a coalescing poll could drop the one tick that caught it |
| `RxTango/java/examples/StorageRingSimulation.java:403` | `concatMapSingle` (no `onBackpressureLatest` — `Observable` source) | **corrected from an initial display-class filing**: each tick computes a control action from sensor readings and *writes* it via `write_attribute` — a dropped tick skips a control decision, not just a display refresh |
| `RxTine/java/examples/PollProperty.java:40` | `onBackpressureLatest().concatMapSingle` | pure display poll |
| `RxTine/java/examples/CalibrationPipeline.java:52` | `concatMapSingle` | write at :59 stays sequential |

`examples/XRayScan.java:149` — already bounded (`maxConcurrency=1`); unchanged, cited as the
in-repo precedent for the Java decision table.

## Java — DO NOT TOUCH (already `concatMapSingle`, per 2.4: edge-sensitive stays serialize, display-class converts)

| File:line | Class | Decision |
|---|---|---|
| `RxTango/demo/scripts/StorageRingDashboard.java:28` | pure display (whole-ring dashboard) | **converted** to `onBackpressureLatest().concatMapSingle(...)` — see FIX-equivalent note below |
| `RxTango/demo/scripts/CorrelatedOrbitSnapshot.java:27` | correlated snapshot print, display-class | **converted** to `onBackpressureLatest().concatMapSingle(...)` |
| `RxTango/demo/scripts/RingBackpressure.java:37` | the backpressure demo itself | unchanged — REVIEW |
| `RxTango/demo/scripts/SmoothedCurrentWriter.java:28-35` | edge-sensitive (writes an orbit correction on a smoothed-average transition) | unchanged — stays `concatMapSingle`, no loss |
| `RxTango/demo/scripts/BeamLossInterlocks.java:23-26` | edge-sensitive (interlock supervisor) | unchanged — stays `concatMapSingle`, no loss |
| `RxTango/demo/lib/RingDevices.java:71` | fan-out serialize helper used by the above | unchanged |

Per 2.4's explicit instruction ("Where `concatMapSingle` backs a pure live display... coalescing
is the more correct choice"), `StorageRingDashboard.java` and `CorrelatedOrbitSnapshot.java` move
to the `onBackpressureLatest()` idiom; the two edge-sensitive scripts do not.

## Java — DO NOT TOUCH (fan-out / chains / non-poll)

`RxTango/java/examples/MultiDeviceSnapshot.java:68` (fan-out fromIterable), fluent-chain sources
(`TangoClient.java`, `TineClient.java`), `RxTango/java/examples/TangoTestRetry.java:97` (error
signal stream inside `retryWhen`, not a read).

---

## Grep proof (post-fix)

`grep -rn "interval" | grep "flat_map"` (Python) / `grep "flatMapSingle"` (Java) /
`grep "flat_map"` (C++) is expected to return only: the two REVIEW backpressure sites per
language, `RxTango/java/examples/TangoTestZipWindow.java`'s three DO-NOT-TOUCH blocks,
`RxTango/demo/scripts/{RingBackpressure,SmoothedCurrentWriter,BeamLossInterlocks}.java`,
`RxTango/java/examples/MultiDeviceSnapshot.java:68` (inner fan-out),
`RxEpics/python/examples/multi_pv_snapshot.py:40` (inner fan-out), and RxCpp's
`iterate(streams).flat_map(identity)` fan-in merges. Every one of those carries an inline comment
stating why it stays.
