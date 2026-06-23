# RxTango/cpp — ReactiveX Contract Verification

The single test deliverable for RxTango/cpp — the C++ analog of
`RxTangoPublisherVerification.java` + `examples/VerifySpec.java` in the Java
subproject (which runs the reactive-streams TCK).

## What it verifies

`verify_contract.cpp` checks that the four RxTango primitives honour the
**ReactiveX Observable contract** — the Rx equivalent of the reactive-streams spec:

| Rule | Description |
|---|---|
| `[C1]` | Grammar: `on_next* (on_error\|on_completed)?` — at most one terminal signal |
| `[C2]` | **Single-shot**: read/write/command emit **exactly one** `on_next` then `on_completed` |
| `[C3]` | No signals after terminal — `on_completed` must silence the stream |
| `[C4]` | Serialized notifications — no concurrent `on_next` (esp. from monitor callback thread) |
| `[C5]` | Dispose stops push notifications — `unsubscribe_event` is called on dispose |
| `[C6]` | Failed observable path: bad device/attr delivers `on_error`, not a crash |

These rules mirror the §-numbered spec comments in `RxTango.java` and
`RxTangoAttributeChangePublisher.java`.

## Running

**Prerequisites:** the Tango docker stack must be running.

```shell
# From RxTango/cpp/
docker compose up -d          # start MariaDB + DatabaseDS + TangoTest

cmake -S . -B build
cmake --build build

./build/tests/verify_contract
# or with explicit device / attribute:
./build/tests/verify_contract tango://localhost:10000/sys/tg_test/1 double_scalar
```

Expected output:

```
RxTango C++ — ReactiveX Observable Contract Verification
Device : tango://localhost:10000/sys/tg_test/1
Attr   : double_scalar

PASS  [C2][C1]  read_attribute: exactly one on_next + on_completed
PASS  [C3]      No on_next signals delivered after on_completed
PASS  [C2]      write_attribute: re-emits written value + on_completed
PASS  [C2]      execute_command: emits argout (DevDouble 2.0 → 4.0) + on_completed
PASS  [C4]      monitor_attribute: serialized (no concurrent on_next)
PASS  [C5]      monitor_attribute: dispose stops notifications
PASS  [C6]      Bad device → on_error (not a crash), no on_completed

All rules PASSED
```

Exit code 0 on success, 1 on any failure — the same contract as `jbang verify-spec@.`.

> **Note on [C5] / monitor:** Tango events require a properly configured ZMQ event
> system.  If the docker TangoTest device doesn't emit PERIODIC events in your
> environment, rule C5 is **SKIP**ped (not FAIL) and the exit code remains 0.
> Rules C1–C4 and C6 are always run.

## Relation to the Java TCK

The Java subproject uses the formal reactive-streams TCK
(`PublisherVerification` from `reactive-streams-tck`) which runs 12 standard
test methods.  There is no equivalent C++ TCK library for `rxcpp::observable`.
This file provides the same assurance by directly asserting the numbered rules
against the live device — explicit is better than implicit.
