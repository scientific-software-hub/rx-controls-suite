# RxEpics/cpp — ReactiveX Contract Verification

The reactive conformance test for RxEpics/cpp — the EPICS analog of `VerifySpec.java`
in the Java subproject.  **This makes RxEpics/cpp the first EPICS subproject in the
suite with a reactive conformance test** (RxEpics/python has none).

## What it verifies

`verify_contract.cpp` checks the **ReactiveX Observable contract** for the three
RxEpics primitives (`read_pv`, `write_pv`, `monitor_pv`):

| Rule | Description |
|---|---|
| `[C1]` | Grammar: `on_next* (on_error\|on_completed)?` — at most one terminal signal |
| `[C2]` | **Single-shot**: `read_pv`/`write_pv` emit **exactly one** `on_next` then `on_completed` |
| `[C3]` | No signals after terminal — `on_completed` must silence the stream |
| `[C4]` | Serialized notifications — no concurrent `on_next` from PVXS callback threads |
| `[C5]` | Dispose stops push notifications — PVXS Monitor handle is destroyed |
| `[C6]` | Failed observable: bad PV name delivers `on_error`, not a crash |

## Running

**Prerequisites:** the EPICS softIoc docker stack must be running.

```shell
# From RxEpics/cpp/
docker compose up -d

export EPICS_PVA_ADDR_LIST=localhost
export EPICS_PVA_AUTO_ADDR_LIST=NO

cmake -S . -B build
cmake --build build

./build/tests/verify_contract
# or with explicit PV:
./build/tests/verify_contract TEST:DOUBLE
```

Expected output:

```
RxEpics C++ — ReactiveX Observable Contract Verification
PV     : TEST:DOUBLE
Monitor: TEST:CALC

PASS  [C2][C1]  read_pv: exactly one on_next + on_completed
PASS  [C3]      No on_next signals delivered after on_completed
PASS  [C2]      write_pv: re-emits written value + on_completed
PASS  [C4]      monitor_pv: serialized (no concurrent on_next)
PASS  [C5]      monitor_pv: dispose stops notifications
PASS  [C6]      Bad PV name → on_error (not a crash), no on_completed

All rules PASSED
```

Exit code 0 on success, 1 on any failure.

> **Note on [C5] / monitor:** Rule C5 reports SKIP (not FAIL) if no updates
> arrive on `TEST:CALC` (e.g. the IOC scan is disabled).  Rules C1–C4 and C6
> are always exercised.

## Test PVs (from docker-compose.yml softIoc)

| PV | Record | Purpose |
|---|---|---|
| `TEST:DOUBLE` | ao | Static double — used for C1/C2/C3/C6 |
| `TEST:CALC` | calc (0.1 s scan) | Oscillating value — used for C4/C5 |
