# CLAUDE.md — RxEpics/cpp

Guidance for Claude Code when working in this directory.

## Build & Run

```bash
# From RxEpics/cpp/
cmake -S . -B build
cmake --build build

# Run the contract verifier against the live softIoc
docker compose up -d
export EPICS_PVA_ADDR_LIST=localhost
export EPICS_PVA_AUTO_ADDR_LIST=NO
./build/tests/verify_contract

# Run an example
./build/examples/read_pv TEST:DOUBLE TEST:LONG
./build/examples/monitor_pv TEST:CALC
./build/examples/pv_pipeline
```

PVXS must be installed system-wide.  RxCpp is fetched by CMake via FetchContent.

## Architecture

**Header-only library** (`include/rxepics/*.hpp`).  No compiled library target.
Namespace: `rxepics`.

**EPICS has no commands** — `EpicsClient` has no `execute()`.  Write to a command PV.

**Function/class hierarchy:**

- `EpicsContext` — Meyers singleton wrapping `pvxs::client::Context`.  Created from
  environment (`EPICS_PVA_*` env vars) on first access.  Free function
  `default_context()` returns the context reference.
- `read_pv<T>(name, ctx) → observable<T>` — single-shot.  Runs `ctx.get(name).exec()->wait(5.0)`
  on a detached `std::thread`.  Extracts `val["value"].as<T>()`.
- `write_pv<T>(name, value, ctx) → observable<T>` — single-shot.  Runs
  `ctx.put(name).set("value", v).exec()->wait(5.0)`.  Re-emits written value.
- `monitor_pv<T>(name, ctx) → observable<T>` — push, never completes.
  Creates a `pvxs::client::Monitor` with a callback lambda (holds the subscriber via
  `shared_ptr`; serializes updates via `shared_ptr<mutex>`).  Dispose destroys the
  Monitor handle, which cancels the PVXS subscription.
- `EpicsClient` — fluent builder holding `rxcpp::observable<std::any>` chain.
  Methods: `read`, `monitor` (first step), `write` (3 overloads), `map`, `subscribe`.

## Key Design Points

- **Single-shot** vs **push**: same split as all other subprojects.
- **Context is passed explicitly** — functions take `pvxs::client::Context& ctx` (default
  = `default_context()`) mirroring Python's explicit `ctx` argument.
- **PVXS Monitor lifetime**: the `pvxs::client::Monitor` handle is kept alive via
  `shared_ptr` until the subscriber unsubscribes; destroying it cancels the subscription.
- **Type template parameter T**: extracted from PVXS `pvxs::Value` via `.as<T>()`.
  Default is `double`.  Ensure `EPICS_PVA_ADDR_LIST` is set before running.

## Test PVs

| PV | Record | Purpose |
|---|---|---|
| `TEST:DOUBLE` | ao | Static double (write/read tests) |
| `TEST:LONG` | longout | Static long |
| `TEST:STRING` | stringout | Static string |
| `TEST:CALC` | calc (0.1s scan) | Oscillating value (monitor tests) |
