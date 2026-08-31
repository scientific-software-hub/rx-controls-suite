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
- `monitor_pv<T>(name, ctx) → observable<T>` — push, never completes.  Built on
  `detail::monitor_updates<E>` (the analog of Python's `_monitor_updates`): creates
  a `std::shared_ptr<pvxs::client::Subscription>` from
  `ctx.monitor(name).maskConnected(true).maskDisconnected(true).event(cb).exec()`,
  holds the subscriber via `shared_ptr`, serializes + **drains** the event queue
  under `shared_ptr<mutex>`.  Dispose destroys the handle → subscription cancelled.
  A per-update conversion failure is written to `std::cerr` and skipped; only an
  `exec()` failure reaches `on_error`.
- `monitor_errors<T>(name, ctx) → observable<PvUpdateError>` — the per-update
  failures `monitor_pv<T>` drops, as in-band values.  Same `detail::monitor_updates`
  plumbing; never completes, never `on_error` for a per-update failure.  Opens its
  **own** PVA subscription (PVXS has no per-parameter Subscription cache like
  caproto's — `monitor_pv` + `monitor_errors` on one PV = two subscriptions).
- `connection_status(name, ctx) → observable<bool>` — PVA link state.  Built on
  `ctx.connect(name).onConnect(...).onDisconnect(...).exec()`
  (`std::shared_ptr<pvxs::client::Connect>`).  Emits a synthetic `false` on
  subscribe, then one value per transition, `.distinct_until_changed()`.  Never
  completes.  The `Connect` handle is dropped only from the unsubscribe lambda
  (its dtor synchronizes with in-flight callbacks — `syncCancel` defaults true).
- `PvUpdateError` (`errors.hpp`) — a bad update as a value: `pv_name`, `cause`
  (`std::exception_ptr`), `timestamp`.  Derives from `std::runtime_error` so it
  composes, but is never thrown — only delivered on `monitor_errors`.
- `EpicsClient` — fluent builder holding `rxcpp::observable<std::any>` chain.
  Methods: `read`, `monitor` (first step), `write` (3 overloads), `map`, `subscribe`.
  Not extended for resilience — Python's `EpicsClient` isn't either.

## Key Design Points

- **Resilience — errors as messages, not terminal `on_error`.** A per-update
  failure (bad payload, an update PVXS rejects) and a connection transition are
  *messages*; only a setup failure (`MonitorBuilder::exec()` throws) is terminal.
  Mirrors `RxEpics/python`'s `monitor_pv` / `monitor_errors` / `connection_status`
  split.  `tests/verify_contract.cpp` rule **C7** locks this in: a transient update
  error must not terminate a long-lived monitor.
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
| `TEST:STRING` | stringout | Static string — also C7: a string pulled `.as<double>()` throws `NoConvert` on non-numeric text, succeeds on `"42"` |
| `TEST:CALC` | calc (0.1s scan) | Oscillating value (monitor tests) |

## PVXS / RxCpp gotchas (hard-won, do not rediscover)

Verified against PVXS 1.5 (`/epics/support/pvxs` in the
`ghcr.io/epics-containers/epics-base-developer:7.0.10ec1` image) and GCC 13.3.

- **`pvxs::client::Monitor` is not a type.** `MonitorBuilder::exec()` returns
  `std::shared_ptr<pvxs::client::Subscription>`; `Monitor` is only an enumerator in
  `Operation::operation_t`.  The pre-#1 `monitor.hpp` used `pvxs::client::Monitor`
  and had therefore never compiled — CI only checked that files exist.
- **PVXS fires `event()` on an empty→non-empty queue transition — you must drain.**
  `pop()` returns an invalid `Value` when the queue is empty; a callback that pops
  once per event stalls after the first update.  Loop `while (auto v = s.pop())`.
  PVXS's own `tools/monitor.cpp` does exactly this.
- **A per-update failure was silently *stalling*, not terminating.** The old
  `catch (...)` in the event lambda swallowed the exception and aborted the drain,
  so the stream froze rather than erroring.  #1's fix surfaces it as a message and
  keeps draining.
- **`maskConnected` / `maskDisconnected` defaults are asymmetric** (`_maskConn =
  true`, `_maskDisconn = false`).  `monitor_updates` sets **both** true: the value
  stream carries values only, link state is `connection_status`'s job.  With both
  masked, anything `pop()` throws is a real error (`RemoteError` / client-side).
- **PVXS ships no CMake config and no `pvxs.pc`.**  `find_package(PVXS)` and
  `pkg_check_modules(pvxs)` both fail against a stock `make`-built tree.
  `CMakeLists.txt` has a third fallback: `-DPVXS_ROOT` + `-DEPICS_BASE`
  (`find_path`/`find_library`, plus EPICS Base `include`, `include/os/Linux`,
  `include/compiler/gcc`).  **Not `PVXS_DIR`** — `find_package(CONFIG)` reserves
  `<pkg>_DIR` and rewrites it to `-NOTFOUND` on a failed config search.
- **RxCpp v4.1.1 + GCC 13.**  (1) RxCpp's own CMake project unconditionally builds
  its test/example targets, which don't compile under GCC 13 — so `CMakeLists.txt`
  fetches RxCpp with `SOURCE_SUBDIR` pointed at a nonexistent dir and defines the
  `rxcpp` INTERFACE target by hand.  (2) `rx-coordination.hpp` forms `decltype`s
  through a null `this`; GCC 13 diagnoses it under `-Wnonnull` and on some paths
  promotes it to an error — the `rxcpp` target carries `-Wno-nonnull
  -Wno-error=nonnull` for GNU.
- **`softIoc` (epics-base) is CA-only.**  PVXS is a PVA client, so it sees nothing
  from the `docker-compose.yml` softIoc.  Run `softIocPVX` (from
  `/epics/support/pvxs/bin/`) for a PVA-visible IOC when exercising
  `verify_contract` locally.
- **Five older examples still do not compile** against real RxCpp/GCC 13:
  `multi_pv_snapshot`, `pv_stats` (`.to_vector()` is not an `observable` member),
  `pv_correlate`, `zip_pvs`, and previously `resilient_monitor` (fixed in #1 via
  `.as_dynamic()` + the `iterate`/`flat_map` merge idiom from `alarm_monitor.cpp`).
  The CI `build` job compiles `verify_contract` + `resilient_monitor` only; the
  rest is separate cleanup.
