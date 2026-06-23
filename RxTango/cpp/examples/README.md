# RxTango/cpp — Live Demo Cookbook

Examples showing the same ReactiveX operator vocabulary in C++ that the Java and Python
subprojects use.  Each example is a standalone CMake executable; all take device URL
and attribute as arguments.

## Prerequisites

```shell
# Tango stack (shared with RxTango/java)
docker compose up -d

# Build everything
cd RxTango/cpp
cmake -S . -B build
cmake --build build
```

## Examples

### Basic — one subscription, one idea

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 1 | `read_attribute` | Single-shot `observable<T>` — one value then complete | `./build/examples/read_attribute [dev] [attr]` |
| 2 | `poll_attribute` | Poll without a loop: `interval · flat_map` | `./build/examples/poll_attribute [dev] [attr] [ms]` |
| 3 | `monitor_attribute` | Push observable backed by Tango events | `./build/examples/monitor_attribute [dev] [attr] [event]` |

### Coordination — multi-source

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 4 | `zip_attributes` | Atomic correlated read: `zip(readA, readB)` | `./build/examples/zip_attributes [dev] [a1] [a2]` |
| 5 | `multi_device_snapshot` | Parallel N-device snapshot: `iterate · flat_map · to_vector` | `./build/examples/multi_device_snapshot [attr] [dev1] [dev2]` |
| 6 | `correlate` | Cross-device pair with diff column | `./build/examples/correlate [dev1] [a1] [dev2] [a2]` |
| 7 | `alarm_monitor` ★ | Fan-in alarm stream: `merge · filter` | `./build/examples/alarm_monitor [threshold] [ms] [dev1] [dev2]` |

### Stream processing — operators on a single stream

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 8  | `sliding_average` ★ | Rolling mean: `buffer(N,1) · map(mean)` | `./build/examples/sliding_average [dev] [attr] [N]` |
| 9  | `throttle` | Rate control: `sample_with_time` | `./build/examples/throttle [dev] [attr] [poll-ms] [display-ms]` |
| 10 | `running_stats` | Live O(1) stats (Welford): `scan` | `./build/examples/running_stats [dev] [attr]` |
| 11 | `stats` | Batch stats: `take(N) · to_vector` | `./build/examples/stats [dev] [attr] [N]` |
| 12 | `backpressure` | Overload strategies: `sample / debounce / buffer` | `./build/examples/backpressure [strategy]` |
| 13 | `retry` | Transient failure recovery: `retry(N)` inside `flat_map` | `./build/examples/retry [strategy]` |
| 14 | `zip_window` | Window-synchronized pair stats | `./build/examples/zip_window [dev] [a1] [a2] [N]` |

### Composition — multi-step pipelines

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 15 | `calibration_pipeline` | Continuous read → calibrate → write | `./build/examples/calibration_pipeline [dev]` |
| 16 | `pipeline` ★ | Fluent 6-step TangoClient chain | `./build/examples/pipeline [dev]` |
| 17 | `fluent_client` | Full TangoClient API showcase | `./build/examples/fluent_client [dev]` |

★ = recommended demos for presentations

## Quick demo (all defaults against local TangoTest)

```shell
docker compose up -d
cmake -S . -B build && cmake --build build

# Basics
./build/examples/read_attribute
./build/examples/poll_attribute
# Reactive-spec conformance
./build/tests/verify_contract
# Showstoppers
./build/examples/pipeline
./build/examples/alarm_monitor
./build/examples/sliding_average
```

## Reactive contract

All examples depend on the same Observable contract verified by `verify_contract`:
- `read_*` / `write_*` / `execute_*` — **single-shot**: one value then `on_completed`.
- `monitor_*` — **push**: values until disposed (`sub.unsubscribe()` tears down the
  Tango event subscription).
- Errors propagate via `on_error`; they do not throw across thread boundaries.

## Mirrors

| C++ example | Python mirror | Java mirror |
|---|---|---|
| `read_attribute.cpp` | `read_attribute.py` | `ReadAttribute.java` |
| `poll_attribute.cpp` | `poll_attribute.py` | `PollAttribute.java` |
| `pipeline.cpp` | `pipeline.py` | `TangoTestPipeline.java` |
| `sliding_average.cpp` | `sliding_average.py` | `TangoTestSlidingAverage.java` |
| *(all others follow the same pattern)* | | |
