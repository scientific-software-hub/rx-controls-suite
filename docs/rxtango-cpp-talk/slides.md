# Reactive Programming for Tango Controls — C++ Edition

**Igor Khokhriakov**
Principal Software Engineer · Hamburg

> RxTango/cpp · same ReactiveX idioms — now in native C++17

---

# Slide 1 — Title

## Reactive Programming for Tango Controls

*C++17 edition — zero-overhead reactive pipelines.*

**github.com/scientific-software-hub/rx-controls-suite**

---
Speaker notes:
C++ audience knows cppTango and DeviceProxy well.  The pain points:
- callbacks in subscribe_event / push_event
- manual thread synchronisation for event callbacks
- no composable operator vocabulary
Skip preamble — show C++ code immediately.

---

# Slide 2 — Pattern 1: Correlated Multi-Attribute Reads

## Beyond sequential DeviceProxy::read_attribute()

> "Every 500 ms, read `double_scalar` and `float_scalar` from TangoTest —
> and only process the pair when BOTH arrive in the same polling window.
> Discard if either fails."

### With today's tools…

- Two sequential `read_attribute()` calls — timing gap opens between them
- Manual `std::thread` + `std::condition_variable` to run them in parallel
- Shared state to pair results; try/catch in each thread

### With Rx — rxcpp::observable<>::zip()

```cpp
rxcpp::observable<>::interval(std::chrono::milliseconds(500))
  .flat_map([](long) {
    // Both reads fire on background threads in parallel
    return rxcpp::observable<>::zip(
      [](double a, float b) { return process(a, b); },
      rxtango::read_attribute<double>(device, "double_scalar"),
      rxtango::read_attribute<float>(device,  "float_scalar")
    );
  })
  .subscribe([](auto result) { publish(result); });
```

✓ If either read fails the pair is dropped — never half-processed.
✓ Zero shared state. Zero condition_variable.

---

# Slide 3 — Pattern 2: Push Stream Processing

## Beyond manual CallBack::push_event() bookkeeping

> "Monitor `double_scalar` at PERIODIC events, compute a 5-sample sliding
> average, write back only when it deviates > 10% from the last written value."

### With today's tools…

- Inherit `Tango::CallBack`, override `push_event()`
- Keep `std::deque<double>` + index + last-written — every time
- Thread-safe access to those fields from the cppTango event thread

### With Rx — monitor_attribute + buffer + filter

```cpp
rxtango::monitor_attribute<double>(device, "double_scalar", "periodic")
  // sliding window — no deque, no index arithmetic
  .buffer(5, 1)
  .filter([](const auto& w) { return (int)w.size() == 5; })
  .map([](const auto& w) {
    return std::accumulate(w.begin(), w.end(), 0.0) / w.size();
  })
  // skip write if within 10% of last value
  .distinct_until_changed([](double prev, double curr) {
    return std::abs(curr - prev) / prev < 0.1;
  })
  .flat_map([](double avg) {
    return rxtango::write_attribute<double>(device, "double_scalar_w", avg);
  })
  .subscribe([](double v) { std::cout << "wrote: " << v << "\n"; });
```

---

# Slide 4 — Pattern 3: Alarm Fan-In

## Beyond per-device polling loops

> "Watch three TangoTest devices. When any one reports a fault, notify immediately."

### With today's tools…

- One `DeviceProxy` + `subscribe_event` per device
- Manual fan-in: shared queue, mutex, or `std::jthread`
- Error isolation requires more shared state

### With Rx — rxcpp::observable<>::merge()

```cpp
rxcpp::observable<>::merge(
  rxtango::monitor_attribute<double>(dev1, "double_scalar"),
  rxtango::monitor_attribute<double>(dev2, "double_scalar"),
  rxtango::monitor_attribute<double>(dev3, "double_scalar")
)
.filter([](double v) { return std::abs(v) > THRESHOLD; })
.subscribe([](double v) { notify_operator(v); });
```

✓ Any one failing device propagates — others continue unaffected.
✓ Serialised by the monitor's internal mutex — no data races.

---

# Slide 5 — RxTango/cpp Data Flow

## Reference implementation

```
cppTango (Tango::DeviceProxy)
        ↓  std::thread + rxcpp::observable<>::create<T>
  read_attribute · write_attribute · execute_command  — single-shot
  monitor_attribute                                   — push, event-backed
        ↓  RxCpp operators
  flat_map · zip · merge · buffer · filter · scan · sample_with_time
        ↓  Application logic — pure functions, no I/O, no shared state
        ↓  write_attribute / downstream
```

Header-only · C++17 · CMake + FetchContent · cppTango · ReactiveX contract verified

---

# Slide 6 — Thank You

**github.com/scientific-software-hub/rx-controls-suite**

AGPL-3.0 · C++17 · CMake · RxCpp · cppTango
