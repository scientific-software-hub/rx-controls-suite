# Reactive Programming for EPICS Controls — C++ Edition

**Igor Khokhriakov**
Principal Software Engineer · Hamburg

> RxEpics/cpp · same ReactiveX idioms — now in native C++17 with PVXS

---

# Slide 1 — Title

## Reactive Programming for EPICS Controls

*C++17 edition — PVXS PVA + RxCpp, zero-overhead pipelines.*

**github.com/scientific-software-hub/rx-controls-suite**

---
Speaker notes:
EPICS C++ audience knows libca / PVXS and caMonitor callbacks well.
Pain: callback spaghetti, manual ring buffers, no cross-PV composition.
No commands in EPICS — everything is a PV.

---

# Slide 2 — Pattern 1: Correlated Multi-PV Reads

## Beyond sequential ca_get / pvxs::client::Context::get()

> "Every 500 ms, read `BEAM:CURRENT` and `ORBIT:XPOS` — and only process the
> pair when BOTH arrive.  Discard if either times out."

### With today's tools…

- Two sequential `ctx.get(pv).exec()->wait(5.0)` calls — timing gap
- `std::thread` pair + `std::promise` / `std::future` to parallelise
- Manual pairing and error handling

### With Rx — rxcpp::observable<>::zip()

```cpp
rxcpp::observable<>::interval(std::chrono::milliseconds(500))
  .flat_map([&ctx](long) {
    return rxcpp::observable<>::zip(
      [](double c, double x) { return process(c, x); },
      rxepics::read_pv<double>("BEAM:CURRENT", ctx),
      rxepics::read_pv<double>("ORBIT:XPOS",   ctx)
    );
  })
  .subscribe([](auto result) { publish(result); });
```

✓ Zero shared state. Zero std::promise.
✓ If either PV is unreachable the pair is silently dropped.

---

# Slide 3 — Pattern 2: Monitor Stream Processing

## Beyond caMonitor callbacks

> "Monitor `TEST:CALC` (10 Hz IOC push), compute a 5-sample sliding average,
> write back only when it deviates > 10% from last written value."

### With today's tools…

- `ctx.monitor(pv).event(callback).exec()` — own ring buffer + threshold variable
- Manual serialisation with `std::mutex` (callback arrives on PVXS thread)
- Same boilerplate every project

### With Rx — monitor_pv + buffer + filter

```cpp
rxepics::monitor_pv<double>("TEST:CALC")
  .buffer(5, 1)
  .filter([](const auto& w) { return (int)w.size() == 5; })
  .map([](const auto& w) {
    return std::accumulate(w.begin(), w.end(), 0.0) / w.size();
  })
  .distinct_until_changed([](double prev, double curr) {
    return std::abs(curr - prev) / prev < 0.1;
  })
  .flat_map([&ctx](double avg) {
    return rxepics::write_pv<double>("TEST:DOUBLE", avg, ctx);
  })
  .subscribe([](double v) { std::cout << "wrote: " << v << "\n"; });
```

---

# Slide 4 — Pattern 3: Alarm Fan-In

## Beyond per-PV caMonitor registrations

> "Watch three PVs. When any one exceeds a threshold, notify."

### With today's tools…

- One `ctx.monitor(pv).event(cb).exec()` per PV
- Shared alarm queue + mutex for fan-in
- No first-class merging of subscriptions

### With Rx — rxcpp::observable<>::merge()

```cpp
rxcpp::observable<>::merge(
  rxepics::monitor_pv<double>("PV:ONE"),
  rxepics::monitor_pv<double>("PV:TWO"),
  rxepics::monitor_pv<double>("PV:THREE")
)
.filter([](double v) { return std::abs(v) > THRESHOLD; })
.subscribe([](double v) { notify_operator(v); });
```

✓ Any one out-of-range PV fires — others continue.
✓ PVXS callbacks are serialised by the monitor's internal mutex.

---

# Slide 5 — RxEpics/cpp Data Flow

## Reference implementation

```
EPICS IOC (CA/PVA via PVXS pvxs::client::Context)
        ↓  std::thread + rxcpp::observable<>::create<T>
  read_pv · write_pv        — single-shot
  monitor_pv                 — push, PVXS monitor-backed
        ↓  RxCpp operators
  flat_map · zip · merge · buffer · filter · scan · sample_with_time
        ↓  Application logic — pure functions
        ↓  write_pv / downstream
```

No commands (EPICS has none — write to a PV instead)
Header-only · C++17 · CMake + FetchContent · PVXS · ReactiveX contract verified
First EPICS subproject in the suite with a reactive conformance test

---

# Slide 6 — Thank You

**github.com/scientific-software-hub/rx-controls-suite**

AGPL-3.0 · C++17 · CMake · RxCpp · PVXS
