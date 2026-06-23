# RxTango/cpp

C++17 reactive wrapper for [Tango Controls](https://www.tango-controls.org/), using
[RxCpp](https://github.com/ReactiveX/RxCpp) `observable<T>` — the same ReactiveX
operator vocabulary as `RxTango/java` and `RxTango/python`.

```cpp
// Poll without a loop; calibrate; write back — no threads, no callbacks
rxcpp::observable<>::interval(std::chrono::milliseconds(500))
    .flat_map([](long) { return rxtango::read_attribute<double>(device, "double_scalar"); })
    .map([](double v) { return std::abs(v) * 2.0 + 1.5; })
    .flat_map([](double v) { return rxtango::write_attribute<double>(device, "double_scalar_w", v); })
    .subscribe([](double v) { std::cout << "wrote: " << v << "\n"; });
```

## Prerequisites

- **C++17** compiler (GCC 9+, Clang 10+)
- **CMake** 3.18+
- **RxCpp** — fetched automatically via `FetchContent` (no install needed)
- **cppTango** — system install, detected via `pkg-config tango`
- **Docker** — for the TangoTest device stack

## Quick start

```shell
cd RxTango/cpp

# Start the Tango stack (shared with RxTango/java)
docker compose up -d

# Build
cmake -S . -B build
cmake --build build

# Run an example
./build/examples/read_attribute tango://localhost:10000/sys/tg_test/1 double_scalar

# Showstopper: fluent 6-step pipeline
./build/examples/pipeline tango://localhost:10000/sys/tg_test/1
```

## Library API

The library is header-only.  Include the umbrella header:

```cpp
#include <rxtango/rxtango.hpp>
```

### `read_attribute<T>(device, name)` → `observable<T>`

Single-shot read.  Emits one value then completes.

```cpp
rxtango::read_attribute<double>(device, "double_scalar")
    .subscribe([](double v) { std::cout << v; });
```

### `write_attribute<T>(device, name, value)` → `observable<T>`

Single-shot write.  Re-emits the written value so writes chain naturally.

```cpp
rxtango::write_attribute<double>(device, "double_scalar_w", 3.14)
    .flat_map([&](double v) { return rxtango::read_attribute<double>(device, "double_scalar_w"); })
    .subscribe([](double v) { std::cout << "confirmed: " << v; });
```

### `execute_command<R,A>(device, cmd, argin)` → `observable<R>`

Single-shot command.  Emits the argout (result).

```cpp
rxtango::execute_command<double, double>(device, "DevDouble", 2.0)
    .subscribe([](double v) { std::cout << v; });   // prints 4.0
```

### `monitor_attribute<T>(device, name, event)` → `observable<T>`

Push observable backed by cppTango event subscription.  Never completes.
Dispose (`.unsubscribe()`) tears down the Tango event subscription.

```cpp
auto sub = rxtango::monitor_attribute<double>(device, "double_scalar", "periodic")
    .subscribe([](double v) { std::cout << v << "\n"; });
// ...
sub.unsubscribe();   // → proxy.unsubscribe_event() called
```

### `TangoContext`

Process-wide DeviceProxy cache.  Proxies are created lazily and reused across all calls.

```cpp
Tango::DeviceProxy& proxy = rxtango::TangoContext::instance().get_proxy(device);
```

### `TangoClient` — fluent builder

Chains multiple operations without intermediate variables.  Nothing executes
until `subscribe()` is called.

```cpp
rxtango::TangoClient()
    .read(device, "double_scalar")
    .map([](std::any v) -> std::any { return std::abs(std::any_cast<double>(v)) * 2.0 + 1.5; })
    .write(device, "double_scalar_w")
    .subscribe(
        [](std::any v) { std::cout << "wrote: " << std::any_cast<double>(v) << "\n"; },
        [](std::exception_ptr e) { /* handle */ },
        []() { std::cout << "done\n"; }
    );
```

Builder methods: `read`, `monitor` (first step only), `write` (use prev / static / callable),
`execute` (with / without argin / callable argin), `map`, `subscribe`.

## Key patterns

### Polling (no loop)
```cpp
rxcpp::observable<>::interval(std::chrono::milliseconds(500))
    .flat_map([](long) { return rxtango::read_attribute<double>(device, attr); })
    .subscribe([](double v) { std::cout << v << "\n"; });
```

### Correlated zip
```cpp
rxcpp::observable<>::zip(
    [](double a, double b) { return std::make_pair(a, b); },
    rxtango::read_attribute<double>(dev, attr1),
    rxtango::read_attribute<double>(dev, attr2)
).subscribe([](auto pair) { /* process pair */ });
```

### Sliding average
```cpp
source.buffer(N, 1)
    .filter([N](const auto& w) { return (int)w.size() == N; })
    .map([](const auto& w) { return std::accumulate(w.begin(), w.end(), 0.0) / w.size(); })
```

### Alarm fan-in
```cpp
rxcpp::observable<>::merge(stream_dev1, stream_dev2, stream_dev3)
    .filter([](double v) { return v > THRESHOLD; })
    .subscribe([](double v) { notify_operator(v); });
```

## Reactive contract verification

Run the contract checker against the live TangoTest device to verify all
wrappers honour the ReactiveX Observable contract:

```shell
docker compose up -d
./build/tests/verify_contract
```

All rules should print **PASS** and exit 0 — the C++ analog of `jbang verify-spec@.`.
See [`tests/README.md`](tests/README.md) for the rule set.

## Architecture

```
cppTango (Tango::DeviceProxy)
        ↓ std::thread + rxcpp::observable<>::create<T>
   read_attribute · write_attribute · execute_command  — single-shot
   monitor_attribute                                   — push, event-backed
        ↓ RxCpp operators: map · zip · merge · buffer · filter · scan · sample
        ↓ Application logic (pure functions)
        ↓ write_attribute / downstream
```

All primitives are **header-only** (`include/rxtango/*.hpp`).  Production code depends
only on RxCpp and cppTango headers.

## Cross-language correspondence

| Feature | Java (`RxTango/java`) | Python (`RxTango/python`) | C++ (`RxTango/cpp`) |
|---|---|---|---|
| Single-shot read | `RxTangoAttribute<T>` | `read_attribute()` | `read_attribute<T>()` |
| Single-shot write | `RxTangoAttributeWrite<T>` | `write_attribute()` | `write_attribute<T>()` |
| Command | `RxTangoCommand<T,V>` | `execute_command()` | `execute_command<R,A>()` |
| Push | `RxTangoAttributeChangePublisher<T>` | `monitor_attribute()` | `monitor_attribute<T>()` |
| Fluent builder | `TangoClient` | `TangoClient` | `TangoClient` |
| Conformance test | reactive-streams TCK (`VerifySpec.java`) | *(n/a)* | `verify_contract` |
| Async model | RxJava `Flowable` / `Single` | asyncio + RxPY | std::thread + RxCpp |

## Project layout

```
RxTango/cpp/
├── CMakeLists.txt           top-level (FetchContent RxCpp + pkg-config tango)
├── README.md                this file
├── CLAUDE.md                Claude Code guide
├── docker-compose.yml       → links to ../java/docker-compose.yml
├── include/rxtango/
│   ├── context.hpp          TangoContext singleton
│   ├── attribute.hpp        read_attribute<T>
│   ├── attribute_write.hpp  write_attribute<T>
│   ├── command.hpp          execute_command<R,A>
│   ├── monitor.hpp          monitor_attribute<T>
│   ├── client.hpp           TangoClient fluent builder
│   └── rxtango.hpp          umbrella include
├── tests/
│   ├── CMakeLists.txt
│   ├── verify_contract.cpp  ReactiveX contract checker
│   └── README.md            rule set documentation
└── examples/
    ├── CMakeLists.txt
    ├── README.md            Live Demo Cookbook
    ├── read_attribute.cpp … pipeline.cpp   (17 examples)
    └── fluent_client.cpp
```
