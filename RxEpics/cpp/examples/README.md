# RxEpics/cpp — Live Demo Cookbook

EPICS PV examples with the same ReactiveX operator vocabulary as the Tango C++ and Python editions.
EPICS has no commands — write to a PV instead.

## Prerequisites

```shell
# EPICS softIoc stack
docker compose up -d

export EPICS_PVA_ADDR_LIST=localhost
export EPICS_PVA_AUTO_ADDR_LIST=NO

# Build everything
cd RxEpics/cpp
cmake -S . -B build
cmake --build build
```

## Examples

### Basic

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 1 | `read_pv` | Single-shot `observable<T>` — one value then complete | `./build/examples/read_pv [pv ...]` |
| 2 | `poll_pv` | Client-side poll: `interval · flat_map` | `./build/examples/poll_pv [pv] [ms]` |
| 3 | `monitor_pv` ★ | IOC-pushed updates (primary streaming primitive) | `./build/examples/monitor_pv [pv]` |

### Coordination

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 4 | `multi_pv_snapshot` | Parallel N-PV snapshot: `iterate · flat_map · to_vector` | `./build/examples/multi_pv_snapshot [pv1] [pv2]` |
| 5 | `pv_correlate` | Cross-PV pair with diff column | `./build/examples/pv_correlate [pv1] [pv2]` |
| 6 | `zip_pvs` | Atomic zip of two PVs | `./build/examples/zip_pvs [pv1] [pv2]` |
| 7 | `alarm_monitor` ★ | Fan-in alarm stream: `merge · filter` | `./build/examples/alarm_monitor [threshold] [pvs...]` |

### Stream processing

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 8  | `pv_sliding_average` ★ | Rolling mean: `buffer(N,1) · map(mean)` | `./build/examples/pv_sliding_average [pv] [N]` |
| 9  | `pv_throttle` | Rate control: `sample_with_time` | `./build/examples/pv_throttle [pv] [ms]` |
| 10 | `pv_running_stats` | Live O(1) stats (Welford): `scan` | `./build/examples/pv_running_stats [pv]` |
| 11 | `pv_stats` | Batch stats: `take(N) · to_vector` | `./build/examples/pv_stats [pv] [N]` |
| 12 | `pv_backpressure` | Overload strategies: `sample / debounce / buffer` | `./build/examples/pv_backpressure [strategy]` |

### Composition

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 13 | `calibration_pipeline` | Continuous read → calibrate → write | `./build/examples/calibration_pipeline [src] [dst]` |
| 14 | `pv_pipeline` ★ | Fluent EpicsClient chain | `./build/examples/pv_pipeline [src] [dst]` |

### Resilience

| # | Example | What it demonstrates | Run |
|---|---------|---------------------|-----|
| 15 | `resilient_monitor` ★ | `monitor_pv` + `monitor_errors` + `connection_status` merged — a bad update or dropped link is a line of output, not a crash | `./build/examples/resilient_monitor [pv]` |

To see it survive an outage: run it, then in another shell
`cd RxEpics/python && docker compose stop epics-ioc` … `docker compose start epics-ioc`.
The link goes DOWN then UP and values resume — no client action.

★ = recommended demos for presentations

## Quick demo

```shell
docker compose up -d
cmake -S . -B build && cmake --build build
export EPICS_PVA_ADDR_LIST=localhost EPICS_PVA_AUTO_ADDR_LIST=NO

./build/examples/read_pv
./build/examples/monitor_pv TEST:CALC
./build/tests/verify_contract
./build/examples/pv_pipeline
./build/examples/pv_sliding_average TEST:CALC 5
```
