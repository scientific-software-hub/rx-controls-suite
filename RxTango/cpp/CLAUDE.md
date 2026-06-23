# CLAUDE.md — RxTango/cpp

Guidance for Claude Code when working in this directory.

## Build & Run

```bash
# Build everything (from RxTango/cpp/)
cmake -S . -B build
cmake --build build

# Run the contract verifier against the live TangoTest
docker compose up -d
./build/tests/verify_contract

# Run an example
./build/examples/read_attribute tango://localhost:10000/sys/tg_test/1 double_scalar
./build/examples/poll_attribute
./build/examples/pipeline
```

RxCpp is fetched by CMake via FetchContent on first build (requires internet access on
the build machine).  cppTango must be installed system-wide (`pkg-config tango` must
resolve).

## Project Layout

```
include/rxtango/   Header-only library (namespace rxtango)
tests/             verify_contract.cpp — contract checker (run against live device)
examples/          17 example binaries, each mirroring a Python/Java counterpart
```

## Architecture

**Header-only library** (`include/rxtango/*.hpp`).  No compiled library target; examples
and tests link directly to the `rxtango` CMake INTERFACE target.

**Class / function hierarchy (namespace `rxtango`):**

- `TangoContext` — Meyers singleton, caches `Tango::DeviceProxy` per device URL.
  Thread-safe via `std::mutex`.  Cleaned up on process exit (static destructor).
- `read_attribute<T>(device, name) → observable<T>` — single-shot, dispatches blocking
  cppTango call on a detached `std::thread` (analog of Python's `run_in_executor`).
- `write_attribute<T>(device, name, value) → observable<T>` — single-shot, re-emits
  written value so writes can chain naturally.
- `execute_command<R,A>(device, cmd, argin) → observable<R>` — single-shot.
- `monitor_attribute<T>(device, name, event) → observable<T>` — push, never completes.
  `detail::EventCallback<T>` (inherits `Tango::CallBack`) serializes concurrent cppTango
  callback threads via `std::mutex`.  Dispose calls `unsubscribe_event`.
- `TangoClient` — fluent builder holding an `rxcpp::observable<std::any>` chain.
  Each builder method appends a `flat_map` step; nothing executes until `subscribe()`.
  `write()` has three overloads: use-previous, static value, and callable.
  `monitor()` must be the first step.

## Key Design Points

- **Single-shot** observables: `read_attribute`, `write_attribute`, `execute_command`
  emit exactly one `on_next` then `on_completed`.  Compose with
  `interval(...).flat_map(...)` for polling.
- **Push** observable: `monitor_attribute` runs until disposed.
- **No framework lock-in**: the library only depends on RxCpp and cppTango headers.
  Examples can use any RxCpp coordinator/scheduler.
- **Type template parameter T**: extracted from `Tango::DeviceAttribute` via `>>`.
  Common types: `double`, `float`, `Tango::DevLong`, `std::string`,
  `std::vector<double>`.  Default is `double`.
- **`TangoClient` type erasure**: the chain stores `rxcpp::observable<std::any>`.
  Use `std::any_cast<double>` inside `map()` lambdas to unwrap values.

## docker-compose.yml

Symlink to `../java/docker-compose.yml` — same SKAO images (MariaDB + DatabaseDS +
TangoTest `sys/tg_test/1`).

## Adding a new example

1. Create `examples/<name>.cpp` following the pattern of an existing example (parse argv,
   build the rx pipeline, block main thread appropriately).
2. Add `<name>` to the `EXAMPLES` list in `examples/CMakeLists.txt`.
3. Document it in `examples/README.md`.
