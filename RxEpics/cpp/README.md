# RxEpics/cpp

C++17 reactive wrapper for [EPICS](https://epics-controls.org/) (via
[PVXS](https://github.com/mdavidsaver/pvxs) PVA client), using
[RxCpp](https://github.com/ReactiveX/RxCpp) `observable<T>` — the same ReactiveX
operator vocabulary as `RxEpics/python`.

> *EPICS is already a streaming system — we just give it the Rx vocabulary.*

```cpp
// Monitor a PV; compute sliding average; write alarm if out of range
rxepics::monitor_pv<double>("TEST:CALC")
    .buffer(5, 1)
    .filter([](const auto& w) { return w.size() == 5; })
    .map([](const auto& w) { return std::accumulate(w.begin(), w.end(), 0.0) / 5; })
    .filter([](double avg) { return std::abs(avg) > 100.0; })
    .subscribe([](double avg) { std::cout << "ALARM: " << avg << "\n"; });
```

**No commands** — EPICS has none.  Write to a command PV (ao/bo record) instead.

## Prerequisites

- **C++17** compiler (GCC 9+, Clang 10+)
- **CMake** 3.18+
- **RxCpp** — fetched automatically via `FetchContent`
- **PVXS** — system install (`find_package(PVXS)` or `pkg-config pvxs`)
- **Docker** — for the EPICS softIoc test stack
- **EPICS_PVA_ADDR_LIST** and **EPICS_PVA_AUTO_ADDR_LIST=NO** env vars

## Quick start

```shell
cd RxEpics/cpp
docker compose up -d      # start softIoc (TEST:CALC, TEST:DOUBLE, TEST:LONG, TEST:STRING)

export EPICS_PVA_ADDR_LIST=localhost
export EPICS_PVA_AUTO_ADDR_LIST=NO

cmake -S . -B build
cmake --build build

./build/examples/read_pv TEST:DOUBLE TEST:LONG
./build/examples/monitor_pv TEST:CALC
./build/examples/pv_pipeline
```

## Library API

```cpp
#include <rxepics/rxepics.hpp>
```

### `read_pv<T>(name, ctx)` → `observable<T>`

Single-shot read.  Emits one value then completes.

```cpp
rxepics::read_pv<double>("TEST:DOUBLE")
    .subscribe([](double v) { std::cout << v; });
```

### `write_pv<T>(name, value, ctx)` → `observable<T>`

Single-shot write.  Re-emits the written value so writes chain naturally.

```cpp
rxepics::write_pv<double>("TEST:DOUBLE", 3.14)
    .flat_map([](double v) { return rxepics::read_pv<double>("TEST:DOUBLE"); })
    .subscribe([](double v) { std::cout << "confirmed: " << v; });
```

### `monitor_pv<T>(name, ctx)` → `observable<T>`

Push observable — the primary streaming primitive.  IOC pushes updates; no client
polling.  Never completes.  Dispose (`.unsubscribe()`) cancels the PVXS subscription.

```cpp
auto sub = rxepics::monitor_pv<double>("TEST:CALC")
    .subscribe([](double v) { std::cout << v << "\n"; });
// ...
sub.unsubscribe();
```

A per-update failure (an unconvertible payload, an update PVXS rejects) is written
as one line to `std::cerr` and skipped — it does **not** terminate the stream.
Only a *setup* failure (the subscription cannot be created) reaches `on_error`.

### `monitor_errors<T>(name, ctx)` → `observable<PvUpdateError>`

The per-update failures `monitor_pv<T>()` drops, as in-band messages instead of
log lines.  Validates the same `T` conversion, never completes, never routes a
per-update failure through `on_error`.

```cpp
rxepics::monitor_errors<double>("TEST:CALC")
    .subscribe([](const rxepics::PvUpdateError& e) { std::cerr << e.what() << "\n"; });
```

> Unlike Python (caproto dedupes subscriptions by parameters), `monitor_pv<T>()`
> and `monitor_errors<T>()` on the same PV open **two** PVA subscriptions.  Share
> one by publishing a single stream (`.publish().ref_count()`).

### `connection_status(name, ctx)` → `observable<bool>`

PVA channel link state as a stream — `true` while connected.  Emits a synthetic
`false` on subscribe, then one value per transition (de-duplicated).  Never
completes; a transition is a message, never an error.

```cpp
rxepics::connection_status("TEST:CALC")
    .subscribe([](bool up) { set_link_led(up); });
```

### `EpicsContext`

Process-wide PVXS context singleton.  Created from `EPICS_PVA_*` env vars.

```cpp
auto& ctx = rxepics::EpicsContext::instance().context();
// or via the free function:
auto& ctx = rxepics::default_context();
```

### `EpicsClient` — fluent builder

```cpp
rxepics::EpicsClient()
    .read("TEST:CALC")
    .map([](std::any v) -> std::any { return std::abs(std::any_cast<double>(v)) * 2.0; })
    .write("TEST:DOUBLE")
    .subscribe(
        [](std::any v) { std::cout << std::any_cast<double>(v) << "\n"; },
        [](std::exception_ptr e) { /* handle */ },
        []() { std::cout << "done\n"; }
    );
```

Builder methods: `read`, `monitor` (first step only), `write` (use prev / static / callable),
`map`, `subscribe`.  No `execute` — EPICS has no commands.

## Resilience — errors as messages, not exceptions that stop the process

This is the design principle behind the suite (Khokhriakov et al., *J. Synchrotron
Rad.* 29, 644–653, 2022), and RxCpp's `on_error` is a *terminal* notification — so
routing a transient failure through it would be the failure that ends the monitor.
RxEpics/cpp splits failures by what they mean, matching `RxEpics/python`:

- A **setup** failure (the PVA subscription cannot be created) is terminal and
  reaches `on_error`.
- A **per-update** failure (an unconvertible payload, an update PVXS rejects) is a
  *message*.  `monitor_pv<T>()` writes it to `std::cerr` and keeps running;
  `monitor_errors<T>(name, ctx)` carries it as a `PvUpdateError` value for callers
  who want it in-band.
- A **connection transition** is a message on `connection_status(name, ctx)` —
  never an error.

**Reconnect is PVXS's job.** With Connected/Disconnected masked on the value
stream, a dropped monitor simply stops yielding until PVXS re-establishes it; no
client-side reconnect operator is needed (as for caproto in `RxEpics/python`).

`examples/resilient_monitor.cpp` merges all three streams into one console view;
`tests/verify_contract.cpp` rule **C7** proves a transient update error does not
terminate a long-lived monitor.

## Key patterns

### Monitor + sliding average
```cpp
rxepics::monitor_pv<double>("TEST:CALC")
    .buffer(N, 1)
    .filter([N](const auto& w) { return (int)w.size() == N; })
    .map([](const auto& w) { return std::accumulate(w.begin(), w.end(), 0.0) / w.size(); })
    .subscribe([](double avg) { std::cout << avg << "\n"; });
```

### Alarm fan-in (multiple PVs)
```cpp
// One monitor per PV, merged into one alarm stream
rxcpp::observable<>::merge(
    rxepics::monitor_pv<double>("PV1").map([](double v){ return std::make_pair("PV1",v); }),
    rxepics::monitor_pv<double>("PV2").map([](double v){ return std::make_pair("PV2",v); })
)
.filter([](auto p) { return std::abs(p.second) > THRESHOLD; })
.subscribe([](auto p) { std::cout << "ALARM " << p.first << " = " << p.second; });
```

## Reactive contract verification

```shell
./build/tests/verify_contract
```

All rules PASS → exits 0.  See [`tests/README.md`](tests/README.md).

## Cross-language correspondence

| Feature | Python (`RxEpics/python`) | C++ (`RxEpics/cpp`) |
|---|---|---|
| Single-shot read | `read_pv()` | `read_pv<T>()` |
| Single-shot write | `write_pv()` | `write_pv<T>()` |
| Push | `monitor_pv()` | `monitor_pv<T>()` |
| Per-update failures as messages | `monitor_errors()` | `monitor_errors<T>()` |
| Link state as a stream | `connection_status()` | `connection_status()` |
| Bad update value type | `PvUpdateError` | `PvUpdateError` |
| Fluent builder | `EpicsClient` | `EpicsClient` |
| Context | `EpicsContext` (caproto) | `EpicsContext` (PVXS) |
| Conformance test | *(none)* | `verify_contract` (C1–C7) |
| Single-shot retry | `retry_with_backoff()` | *(not ported)* |

## Architecture

```
EPICS IOC (CA/PVA via PVXS)
        ↓ std::thread + rxcpp::observable<>::create<T>
   read_pv · write_pv        — single-shot
   monitor_pv                 — push, PVXS monitor-backed
        ↓ RxCpp operators: map · zip · merge · buffer · filter · scan · sample
        ↓ Application logic
        ↓ write_pv / downstream
```

## Project layout

```
RxEpics/cpp/
├── CMakeLists.txt
├── README.md
├── CLAUDE.md
├── docker-compose.yml → ../python/docker-compose.yml
├── include/rxepics/
│   ├── context.hpp       EpicsContext singleton (PVXS)
│   ├── channel.hpp       read_pv<T>
│   ├── channel_write.hpp write_pv<T>
│   ├── monitor.hpp       monitor_pv<T>, monitor_errors<T>
│   ├── connection.hpp    connection_status
│   ├── errors.hpp        PvUpdateError
│   ├── client.hpp        EpicsClient fluent builder
│   └── rxepics.hpp       umbrella include
├── tests/
│   ├── CMakeLists.txt
│   ├── verify_contract.cpp   (C1–C7)
│   └── README.md
└── examples/
    ├── CMakeLists.txt
    ├── README.md
    ├── resilient_monitor.cpp  values + errors + link state, merged
    └── *.cpp  (15 examples)
```
