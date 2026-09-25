# CHANGES — poll-operator correctness, EPICS resource ownership, timestamped correlation, docs

Branch `fix/poll-correctness-and-ca-ownership`. This log covers the whole branch: Task A
(operator correctness), Task B (EPICS CA resource ownership), Task D (timestamped readings and
correlation), Task C (docs). Commits are small and single-concern; this file summarizes the
branch as a whole, what was left for a human, and what could not be executed in this
environment.

## Corrections to the original brief, found and verified during implementation

The brief's classification table (§2.5) and its Task D design were the starting point, not the
final word — several rows didn't survive contact with the actual code or the actual installed
libraries. Each of these changed what got fixed and how:

1. **`ops.exhaust_map` does not exist in RxPY.** Verified against the installed `reactivex`
   4.1.0 and the `reactivex` 5.1.0 wheel (what a fresh `reactivex>=4.0` install resolves to on
   Python 3.14). Neither has it. The exhaust idiom throughout this branch is
   `ops.map(read) + ops.exclusive()`, smoke-tested against a jittered source before being
   applied anywhere.
2. **RxJava 3.1.8 has no `exhaustMap` either**, confirmed against the real jar downloaded from
   Maven Central. It does have `switchMapSingle` (switch, not exhaust — wrong semantics for a
   display poll, since it cancels the in-flight read) and `onBackpressureLatest()` on
   `Flowable` (not on `Observable`, which has no backpressure protocol to coalesce). The Java
   exhaust idiom is `onBackpressureLatest().concatMapSingle(...)`, generalizing the repo's own
   existing precedent at `examples/XRayScan.java:134,149`.
3. **`data_type='time'` is confirmed for caproto**, end-to-end against a real caproto IOC
   spawned in this environment (not just read from source): `PV.read(data_type='time')` and
   `PV.subscribe(data_type='time')` both work, and `response.metadata.timestamp`/`.severity`
   are populated as documented. No `# VERIFY:` comment was needed anywhere in the EPICS half of
   Task D.
4. **`data_type='time'` changes caproto's Subscription dedup key.** `PV.subscribe` caches on
   the full bound-argument signature including `data_type`. `monitor_pv`, `monitor_pv_ts`, and
   `monitor_errors` all now request `'time'` together, so they still share one CA subscription
   — the existing `test_monitor_pv_and_monitor_errors_share_one_subscription` test still passes
   unmodified as the proof.
5. **`monitor.py`'s original `dispose()` had a real bug the brief never named**: it called
   `registration.clear()`, which tears down *every* callback on the shared `Subscription` —
   so disposing `monitor_pv` silently killed a co-subscribed `monitor_errors` on the same PV.
   Fixed as part of Task B's subscription-scoped pinning (which needed per-callback removal
   anyway); a regression test (`test_monitor_pv_dispose_does_not_kill_sibling_monitor_errors`)
   was verified to fail against the old `clear()` behavior before being committed.
6. **`demo/dectris-integration/facility_bridge.py:56` was mis-filed as DO-NOT-TOUCH** in the
   brief. It mirrors `ring_health` into 4 `write_pv` calls at 2 Hz — a write, not an independent
   read fan-out — and has the identical unordered-write hazard as the shutter supervisors.
   Reclassified and fixed (`concat_map`).
7. **`read_pv`/`write_pv` had zero unit tests** before this branch (confirmed by grep — nothing
   in `RxEpics/python/tests/` mentioned them). `test_channel.py` is new.
8. **PyTango was verified directly**, not left as a `# VERIFY:` guess: `tango.AttrQuality`
   members are `ATTR_VALID/ATTR_ALARM/ATTR_WARNING/ATTR_CHANGING/ATTR_INVALID`;
   `DeviceAttribute.time.totime()` returns a float POSIX timestamp; `DeviceAttribute` exposes
   `.time`/`.quality` unconditionally (no request flag needed, unlike caproto).
9. **Several audit rows filed as display-class (exhaust) were actually edge-sensitive** once
   traced to their real consumers, and were corrected to `concat_map`/`concatMapSingle`
   instead: `facility.py`'s `ring_health` (feeds `guarded_scan.py`'s interlock abort trigger),
   `demo/dectris-integration/facilities.py`'s `EpicsFacility` health poll (same role),
   `demo/synchrotron-beamline/bluesky/live_strip.py`'s poll (tracks discrete scan events into
   counters), and Java's `BeamLossScenario.java`/`StorageRingSimulation.java` (the first is
   explicitly an alarm-propagation demo by its own docstring; the second writes a computed
   control action every tick). Conversely, `pv_throttle.py` and its Tango/C++/Java counterparts
   were initially filed as exhaust but their own text commits to reading at full poll rate — the
   coalescing is `sample()`/`throttleLast()` downstream, so they became `concat_map` instead.
10. **Several rows filed as FIX had no `rx.interval` at all** once the actual file was read:
    `guarded_scan.py`'s per-projection acquire steps, `scan_core.py`'s setup/teardown writes,
    `tomography_scan.py`'s write chain, and `RxTango/python/examples/calibration_pipeline.py`
    (no interval anywhere in that file) are single-shot "andThen" sequences invoked once per
    projection/scan, not poll sites. Left as `flat_map` — that operator means "andThen" there,
    not "poll".
11. **RxTango/cpp's `retry.cpp` "inner branch unchanged" filing was wrong.** Both branches'
    outer flatten is fed directly by the same `interval`; only the nested `.retry()` call is
    DO NOT TOUCH. Both branches now use `concat_map`.

Every one of these corrections is recorded inline in `docs/poll-operator-audit.md` at the row
it changed, with a `**corrected from an initial ... filing**` note, not silently overwritten.

## Task A — poll operator correctness

`docs/poll-operator-audit.md` is the full file-by-file classification (FIX / REVIEW / JUDGMENT /
DO NOT TOUCH) with the chosen operator and rationale per site — read it for the complete list.
Summary of what changed, by language:

- **Python**: 34 read-poll sites and 7 write-ordering sites converted, split roughly evenly
  between `map(read) + ops.exclusive()` (pure display polls — `poll_pv.py`, `poll_attribute.py`,
  `multi_pv_snapshot.py`'s outer wrapper, `live_dashboard.py`, `poll_until` in both
  `facility.py` and `tomography_scan.py`, the query-cache pollers, `scan_service.py`'s dashboard
  feed) and `concat_map` (windows/stats/alarms/writes that must not drop or reorder a sample —
  `pv_sliding_average.py`, `pv_running_stats.py`, `pv_stats.py`, `alarm_monitor.py` in both
  bindings, `pv_throttle.py`, `retry.py`, `ring_health`, the three shutter supervisors, the
  Bluesky document mirror, `facility_bridge.py`). One genuine bug fixed as a side effect while
  converting `RxEpics/python/examples/alarm_monitor.py`: the per-PV lambda captured `pv_name` by
  reference from the list-comprehension loop variable with no default-arg binding, so every
  stream would have ended up polling only the *last* PV in the list once actually invoked
  (verified with a standalone Python repro before fixing).
- **C++**: 16 sites converted to `concat_map` (RxCpp has no exhaust operator; per your decision,
  no hand-rolled coalescing helper was built this pass). Two stale file-header doc comments
  (`retry.cpp`, `calibration_pipeline.cpp`) still naming `flat_map` were caught by the
  grep-proof pass and fixed in a follow-up commit.
- **Java**: 20 `flatMapSingle` poll sites converted to `concatMapSingle`; the display-class
  subset (`PollAttribute.java`, `RxTine`'s `PollProperty.java`, `MultiDeviceSnapshot.java`'s
  outer wrapper, and — per 2.4 — `RxTango/demo/scripts/{StorageRingDashboard,
  CorrelatedOrbitSnapshot}.java`) additionally gained `onBackpressureLatest()`. Two Java sites
  stay unchanged with a REVIEW comment (`TangoTestBackpressure.java`, the repo's own backpressure
  demo); `TangoTestZipWindow.java`'s three patterns (shielded zip / combineLatest / windowed
  buffer) stay unchanged — that file already interrogates the zip/combineLatest/buffer tradeoffs
  honestly, which is the audit's own DO-NOT-TOUCH criterion.
- REVIEW sites (an unbounded fast producer is the entire point of the demo) were left as
  `flat_map`/`flatMapSingle` in all three languages, each with an inline comment saying so:
  `pv_backpressure.py`, `RxTango/python/examples/backpressure.py`,
  `RxTango/cpp/examples/backpressure.cpp`, `RxTango/java/examples/TangoTestBackpressure.java`.

## Task B — EPICS CA resource ownership

`RxEpics/python/src/rxepics/_ca_source.py` (new) extracts the plumbing `monitor.py` and
`connection.py` duplicated, in two commits: first a behavior-preserving extraction (still the
old process-global `_KEEPALIVE` set, still `monitor.py`'s buggy `clear()` teardown — verified
green against the unchanged 20-test baseline), then the actual fix — pin the callback on the CA
registration object itself (`Subscription`/`CallbackHandler`, both plain objects with no
`__slots__`), keyed by the `add_callback` token, and switch `monitor.py`'s teardown from
`clear()` to `remove_callback(token)`. Because caproto never evicts a cached `Subscription` from
`PV.subscriptions`, the registration object — and its pin dict — is reused across repeated
create/dispose cycles against the same PV rather than growing per cycle; disposal is no longer
required for correctness. A setup/dispose race (dispose arriving between `add_callback` and the
pin write) is closed with a post-registration re-check.

Two new regression tests: `test_pin_registry_bounded_across_create_dispose_cycles` (~1000
subscribe+dispose cycles, pin dict back to empty) and
`test_monitor_pv_dispose_does_not_kill_sibling_monitor_errors` (verified to fail against the
pre-fix `clear()` teardown before being committed — a real regression test, not a decorative
one). `conftest.py`'s `FakeSubscription.remove_callback` was made `async def` to match caproto's
real asyncio-client contract, which it had been silently misrepresenting.

## Task D — timestamped readings and correlation by time

`Reading(value, ts, quality)` — one dataclass per package (`rxepics.reading.Reading`,
`rxtango.reading.Reading`), deliberately not shared across packages since each carries its own
control system's native quality vocabulary (caproto `AlarmSeverity`; Tango `AttrQuality`).
`read_pv_ts`/`monitor_pv_ts`/`read_attribute_ts`/`monitor_attribute_ts` are new; `read_pv`,
`monitor_pv`, `read_attribute`, `monitor_attribute` are now thin `.pipe(ops.map(lambda r:
r.value))` projections of their `_ts` siblings — same float/value API, verified by the existing
test suites passing unchanged plus new "is a projection of" tests. `monitor_attribute_ts` also
fixes a one-field-too-deep unwrap: `event_data.attr_value` is already a full `DeviceAttribute`,
not just a bare value holder.

`correlate_snapshot(*sources, tolerance_s=None, on_violation="drop")` (in
`rxepics.correlate`/`rxtango.correlate`, identical implementations) zips N `_ts` sources into
`Correlated(values, skew, violated)`, where `skew = max(ts) - min(ts)` across the tuple's source
timestamps. `on_violation="flag"` emits violating tuples with `violated=True` instead of
dropping them. The default `is_valid` recognizes `AlarmSeverity.NO_ALARM`/`AttrQuality.
ATTR_VALID` *by enum member name*, so one `correlate_snapshot` call can correlate an EPICS
`Reading` against a Tango `Reading` (used in `examples/tango_epics_normalize.py`) without either
package importing the other's quality enum. `correlate_latest` is the `combine_latest` sibling
for correlating monitors; its docstring states plainly that true time-bucketing is a larger
design, not implemented this pass, per the brief's own scope note.

Applied at the audited correlation sites: `RxEpics/python/examples/{pv_correlate,zip_pvs}.py`,
`RxTango/python/examples/{correlate,zip_attributes}.py`, and
`examples/tango_epics_normalize.py` (both demos, the cross-package case).
`RxTango/python/examples/zip_window.py` doesn't fit `correlate_snapshot`'s shape (it pairs two
*buffered lists* by position, not two single readings), so it applies the same measured-skew
idea directly — `abs(a.ts - b.ts)` per same-index pair — and its docstring was corrected from
"synchronise" to describe what a count-based pairing actually guarantees. Heterogeneous
snapshots (`ring_health`, `live_dashboard.py`'s 46 reads, `guarded_scan.py`'s five-way
cross-system zip) were left as plain `zip` deliberately — they're a dashboard/frame snapshot,
not a simultaneity claim, and `correlate_snapshot` is not the right tool for "read five
unrelated things this tick."

C++ gets a design, not an implementation: `// TODO(ts):` blocks in `RxEpics/cpp/include/
rxepics/channel.hpp` and `RxTango/cpp/include/rxtango/attribute.hpp` record what a `Reading<T>`
mirror would need (PVXS NTScalar `timeStamp`/`alarm`; Tango `DeviceAttribute::get_date()`/
`get_quality()`) and explicitly say it wasn't implemented or compiled — no cmake/PVXS/cppTango
toolchain in this environment. The corresponding C++ example READMEs were reworded to stop
claiming simultaneity ("atomic zip") the two Python/Java bindings no longer claim either.

## Task C — docs

Three commits: the 3 headline READMEs (root, `RxEpics/python`, `RxTango/python` — a new
"Polling semantics" section with the decision table and transition-loss caveat, a new
"Correlation and timestamps" section, `monitor_pv`'s cold-in-Rx/warm-on-wire behavior documented
against `monitor_attribute`'s cold-with-no-dedup-layer counterpart); every example README in
every language (operator names and "atomic pair"/"in sync" claims corrected to match the
now-fixed example code); and all nine conference decks (`slides.md` + a hand-maintained
`index.html` each, so every snippet existed twice and both copies needed the same fix). The
`combined-demo-talk` deck had the most sites, including the orbit-drift-quality slide's "exact
moment... no timestamp correlation... co-temporaneously... atomically correct" claims, rewritten
to state plainly that a five-way heterogeneous zip guarantees no half-written frame, not
simultaneity, and to point at `correlate_snapshot` as where that gap is actually measured.

Left unchanged, correctly: every "no built-in atomic multi-PV/attribute/property read"
pain-point bullet across the decks — these describe a real limitation of the underlying
protocol (CA/TINE/PVXS/Tango), not a claim this library makes.

## Verification — run, not assumed

**Python** (all six suites, fresh venvs built on Python 3.14 since the pre-existing
`RxEpics/python/.venv` was broken — `pyvenv.cfg` declared 3.12.3 but the symlinked interpreter
now resolves to 3.14.4 with no matching site-packages; rebuilt in place, `pytango`/`caproto`/
`reactivex` all ship cp314/py3 wheels):

| Suite | Baseline | Final | New tests |
|---|---|---|---|
| `RxEpics/python` | 20 passed, 1 deselected | 31 passed, 1 deselected | `test_channel.py` (3), `test_correlate.py` (6), `test_pin_registry_bounded_across_create_dispose_cycles`, sibling-independence test |
| `RxEpics/python` integration (`-m integration`, real caproto IOC spawned) | 1 passed | 1 passed | — |
| `RxTango/python` | 33 passed | 43 passed | `test_attribute.py`/`test_monitor.py` `_ts` and projection tests (4), `test_correlate.py` (6) |
| `RxDectris/python` | 23 passed | 23 passed | — (only file touched was `status.py`'s operator/docstring) |
| `demo/reactive-query-cache` | 7 passed | 7 passed | — |
| `demo/workflow-engines` | 23 passed | 23 passed | — |
| `demo/dectris-integration` | 6 passed | 6 passed | — |

No test was weakened or deleted to make it pass; `test_monitor_dispose_awaits_clear_without_
warning` was renamed and its assertion tightened (asserts the specific callback was removed and
the Subscription was *not* wholesale-cleared, replacing an assertion that would have silently
passed under the old buggy behavior too).

**C++** — **not built**. `cmake` and `pkg-config` are both absent from this environment, and
RxCpp/cppTango/PVXS are not vendored here, so `verify_contract` was not built or run and none of
the `concat_map` edits were compiled. Verified instead by: bracket-balance checking every edited
file, matching each site to its already-tested Python/Java counterpart's reasoning, and
confirming (per `RxEpics/cpp/CLAUDE.md`'s own notes) that `pv_stats.cpp`/`pv_correlate.cpp` were
already non-compiling against a real RxCpp/GCC 13 build for unrelated pre-existing reasons
(`.to_vector()` is not an observable member) before this branch, so this branch does not change
that.

**Java** — **not executed**. `jbang` is present, and TINE/`de.hereon.tango` jars exist in
`~/.m2`, but the scripts declare `//REPOS jtango=https://maven.pkg.github.com/scientific-
software-hub/JTango` for `org.waltz.tango:ez`/`tangorb`, and `~/.m2/settings.xml` only has
credentials under server ids `github`/`ghcr.io` — an id mismatch, not something this branch
should try to patch (it touches credential configuration outside this task's scope). Verified
instead by downloading the real `io.reactivex.rxjava3:rxjava:3.1.8` jar from Maven Central (no
auth needed there) and confirming `concatMapSingle`, `onBackpressureLatest()`, and
`switchMapSingle`'s real signatures via `javap` before relying on them — see correction #2 above.

**Grep proof** — `grep -rn flat_map` (and the Java/C++ equivalents) across every `.py`/`.cpp`/
`.hpp`/`.java` file was walked by hand; every surviving hit is one of: a corrective comment
explaining the fix, a REVIEW site (backpressure demos) with its own comment, or a genuine
DO-NOT-TOUCH site (fan-out concurrency, a fluent-builder "andThen" chain, retry internals, or
`TangoTestZipWindow.java`'s deliberate tradeoff exploration). No bare, unexplained `flat_map`/
`flatMapSingle` remains on a poll-shaped site anywhere in the tree.

## Out of scope, not touched

Karabo (`RxKarabo-plan.md`), licensing/packaging strategy, any new backend, the `RxLoop`
cross-thread redesign, and full time-bucketing for the push-correlation case — all per the
brief's own §7.

## Follow-ups (found during the audit, not fixed — out of this pass's scope)

- **`RxTango/python/src/rxtango/monitor.py`'s event callback swallows every exception silently**
  (`except Exception: pass` around `loop.call_soon_threadsafe(observer.on_next, value)`). A
  malformed event, or an exception inside a downstream synchronous operator run on the event
  loop, disappears with no log line. `monitor_attribute_ts`'s new `extract()` call sits inside
  this same swallowed `try`, so a `.time`/`.quality` access failure would also vanish silently —
  worth tightening in a follow-up pass, ideally mirroring `RxEpics/python/src/rxepics/
  monitor.py`'s WARNING-log-and-continue pattern instead of a bare `pass`.
- **`RxEpics/python/src/rxepics/context.py`'s `EpicsContext.close()` never calls
  `ctx.disconnect()`** on the underlying caproto `Context` — it clears the PV cache and drops the
  reference, but the caproto `Context`'s background tasks/sockets are left for the garbage
  collector and `atexit`, not explicitly torn down.
- **Full time-bucketing for push-correlation** (§4.3 of the brief) — `correlate_latest`'s
  `combine_latest`-based approach is the documented pragmatic version; grouping updates into
  aligned time windows before correlating is a larger design, explicitly deferred.
- **A C++ `Reading<T>`/`read_*_ts<T>()` mirror** — designed in the `// TODO(ts):` header
  comments, not implemented; needs a host with cmake + PVXS + cppTango to build and verify the
  exact PVXS NTScalar field path (`val["timeStamp"]["secondsPastEpoch"]`-style) before wiring it
  up, since that specific path was not verified in this environment.
- **A caproto-internal wart, observed but not caused by this branch**: killing a `monitor_pv`
  subscription's callback via weakref GC (before this branch's pinning fix) triggers caproto's
  own `CallbackHandler.add_callback`'s `removed` finalizer, which calls the now-async (in
  caproto's asyncio client) `Subscription.remove_callback` without awaiting it — a
  `RuntimeWarning: coroutine ... was never awaited` from inside caproto itself, observed while
  verifying `data_type='time'` against a live IOC. The subscription-scoped pinning this branch
  adds means a pinned callback never dies via weakref in the first place, so this path shouldn't
  be hit in practice, but it's a latent caproto-library issue, not an rx-controls-suite one.
