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
| Fluent builder | `EpicsClient` | `EpicsClient` |
| Context | `EpicsContext` (caproto) | `EpicsContext` (PVXS) |
| Conformance test | *(none)* | `verify_contract` |

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
│   ├── monitor.hpp       monitor_pv<T>
│   ├── client.hpp        EpicsClient fluent builder
│   └── rxepics.hpp       umbrella include
├── tests/
│   ├── CMakeLists.txt
│   ├── verify_contract.cpp
│   └── README.md
└── examples/
    ├── CMakeLists.txt
    ├── README.md
    └── *.cpp  (14 examples)
```
