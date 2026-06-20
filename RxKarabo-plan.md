# Plan: Add RxKarabo (Python) to rx-controls-suite

## Context

The suite (`rx-controls-suite`) demonstrates the **same ReactiveX operator vocabulary**
(read / write / monitor / poll / zip / sliding-average / fluent pipelines) across
multiple control-system platforms — currently Tango (Java + Python), EPICS (Python),
and TINE (Java). The goal here is to add **Karabo**, the SCADA framework developed and
used at **European XFEL**, as a new platform so the talk story ("same idioms, any
control system") extends to the XFEL community.

**Decisions made with the user:**
- **Backend:** wrap Karabo's **middlelayer** device-proxy API, **mock-first** — the Karabo
  framework is not pip-installable (conda distribution from European XFEL), so examples
  and tests run against an in-repo fake/simulator. This keeps full read/write/monitor/slot
  symmetry with the rest of the suite.
- **Language:** **Python only** (Karabo's client ecosystem is Python/C++; the middlelayer
  API is asyncio-native; there is no first-class Karabo Java client).
- **Scope:** module + examples + README (runnable blocks) + presentation under `docs/`.
  **Skip** suite-level wiring for now (top-level README row, `.github/workflows`, `CITATION.cff`).

Karabo terminology: devices expose **properties** (read/write values) and **slots**
(callable commands — the analog of Tango commands). Because Karabo has slots, RxKarabo
mirrors **`RxTango/python`** (which has `command.py`) more closely than RxEpics.

## Template to mirror

`RxTango/python` is the primary reference — copy its structure and idioms:
- Each source primitive is a thin `rx.create(subscribe)` wrapper around an async backend
  call; single-shot sources emit one value + `on_completed`; the monitor returns a
  `dispose()`. See `RxTango/python/src/rxtango/attribute.py`, `command.py`, `monitor.py`,
  `client.py`, `context.py`.
- Tests use a hand-written fake injected by patching the context locator, driven by
  `asyncio.run` + `asyncio.Event` + `AsyncIOScheduler`. See `RxTango/python/tests/conftest.py`.
- `pyproject.toml`: hatchling, `src/` layout, `dev = ["pytest"]` extra. See
  `RxTango/python/pyproject.toml`.
- Two-tier README: main README (principles / API / tables) + `examples/README.md`
  "Live Demo Playbook". Docs decks: `docs/rxtine-talk/{slides.md,index.html}`.

## Module layout to create

```
RxKarabo/python/
  pyproject.toml          name="rxkarabo", deps ["reactivex>=4.0"]; dev=["pytest"]
  .gitignore              (copy RxTango/python/.gitignore)
  README.md               main docs
  CLAUDE.md               (optional) per-module agent guide, light
  src/rxkarabo/
    __init__.py           export read_property, write_property, execute_slot,
                          monitor_property, KaraboContext, KaraboClient, use_simulator
    context.py            KaraboContext (proxy cache locator) + KaraboProxy adapter
    property.py           read_property(device, prop) -> Observable  (single-shot)
    property_write.py     write_property(device, prop, value) -> Observable (single-shot)
    slot.py               execute_slot(device, slot, arg=None) -> Observable (single-shot)
    monitor.py            monitor_property(device, prop) -> Observable (push)
    client.py             KaraboClient fluent builder (read/monitor/write/execute/map)
    sim.py                SimulatedKaraboProxy — makes examples/README runnable offline
  tests/
    conftest.py           FakeKaraboProxy (+ fire()) + fixtures (mirror RxTango conftest)
    test_property.py  test_property_write.py  test_slot.py
    test_monitor.py   test_client.py
  examples/
    README.md             "Live Demo Playbook" (numbered, tagline + run cmd + Key code)
    read_property.py  poll_property.py  monitor_property.py
    multi_device_snapshot.py  zip_properties.py  execute_slot.py
    running_stats.py  sliding_average.py  throttle.py
    pipeline.py  fluent_client.py
```

### Backend contract (the seam between real Karabo and the fake)

All backend access funnels through `KaraboContext.get_proxy(device)` (async), returning an
object exposing exactly four methods — the only surface the wrappers and tests depend on:

- `get(prop)` → current property value
- `async set(prop, value)` → write a property
- `async execute(slot, arg=None)` → call a slot, return its result
- `on_change(prop, callback) -> unregister()` → register a change listener (push)

`context.py` provides two implementations of this contract:
- **`KaraboProxy`** (real adapter) — wraps middlelayer: `connectDevice` for the proxy,
  property access `proxy.<prop>.value` for `get`, `setWait` for `set`, awaiting the slot
  attribute for `execute`, and a `background` loop over `waitUntilNew(proxy.<prop>)` for
  `on_change`. Imports of `karabo.middlelayer` are **lazy** (inside methods) so the package
  imports cleanly without Karabo installed. Documented as illustrative/best-effort since it
  can't be CI-tested here.
- **`SimulatedKaraboProxy`** (`sim.py`) — generates a sine-like value per property, accepts
  writes/slots, and pushes periodic `on_change` updates via an asyncio task. Activated by
  `KaraboContext.use_simulator()` or the `RXKARABO_SIM=1` env var.

This makes the README's run blocks genuinely runnable with **no Karabo install** — the
in-process simulator is RxKarabo's analog of the TangoTest / soft-IOC / jsineServer docker
backends the other modules use. Examples default to simulator mode (with a one-line note on
pointing at a real `deviceId`).

### Wrapper idioms (mirror RxTango exactly)

- `property.py` / `property_write.py` / `slot.py`: `rx.create(subscribe)` →
  `asyncio.ensure_future(_op())` → `await KaraboContext.get_proxy(device)` then
  `get`/`set`/`execute`; `observer.on_next(value); observer.on_completed()`; exceptions →
  `observer.on_error`. (Middlelayer is async-native, so `await` directly — no
  `run_in_executor`, unlike PyTango.)
- `monitor.py`: lazily get proxy, `unregister = proxy.on_change(prop, callback)`; callback
  dispatches via `loop.call_soon_threadsafe(observer.on_next, value)`; `dispose()` calls
  `unregister()`. Never completes on its own. Mirror `rxtango/monitor.py`.
- `client.py`: copy `TangoClient` verbatim, renaming `read`→property read,
  `execute`→`execute_slot`, `monitor` must be first step. Keep the same lazy
  `flat_map`-chaining and `subscribe(on_next, on_error, on_completed, scheduler)`.

### Tests (mock-first)

Copy `RxTango/python/tests/conftest.py` → `FakeKaraboProxy` implementing the 4-method
contract with a `fire(prop, value)` to drive `on_change` callbacks synchronously. Each test
runs an `async def run()` under `asyncio.run`, patches `KaraboContext.get_proxy` to return
the fake, and asserts via `on_next`/`on_error`/`on_completed` collector lists with an
`asyncio.Event` + `asyncio.wait_for(..., timeout=2.0)`. Cover: single read, write records
value, slot returns result, monitor emits on `fire` and `dispose` unregisters, error
propagation (`get_proxy` raises), and a fluent `KaraboClient` read→map→write chain.

## Presentation under docs/

Create `docs/rxkarabo-talk/{slides.md, index.html}` mirroring `docs/rxtine-talk/`:
- **`slides.md`**: plain Markdown, `---`-separated. Intro (H1 title, `**Igor Khokhriakov**`
  / `Principal Software Engineer · Hamburg`, `>` tagline), then `# Slide N — …` pattern
  slides (scenario `>` quote, "With today's tools…" pain bullets, "With Rx — <operator>"
  python fenced block), speaker notes, closing "Thank You" slide
  (`github.com/scientific-software-hub/rx-controls-suite`, `AGPL-3.0 · Python 3.10+ · uv ·
  RxPY v4 · Karabo middlelayer`).
- **`index.html`**: clone the rxtine deck's single-file bespoke HTML — reuse the `:root`
  palette (navy `#1a3a5c` / orange `#e87722` / …), `font-size:150%`, `.slide`/`.slide active`
  with `show(n)` JS navigator (Arrow/Space/`f`/swipe), `.logo-mark` "Rx", `N / 6` numbering,
  `.two-col` `.panel` pattern slides with `.label-navy`/`.label-orange`/`.label-green`,
  highlight.js via cdnjs with `language-python`, `#progress-bar`, `#nav-hint`. Add a
  Thank-You cross-link card to a sibling talk.
- Story beats (XFEL-flavored): poll a property, monitor property changes (`on_change`),
  zip two device properties into a correlated stream, sliding-average / throttle a noisy
  reading, and a read→calibrate→write fluent pipeline.
- *(Optional, borderline suite-wiring — confirm at execution if desired):* add a talk card
  to `docs/index.html`.

## Verification

1. `cd RxKarabo/python && uv venv && uv pip install -e ".[dev]"`.
2. **Tests:** `uv run pytest -q` — all green (pure mock, no Karabo needed).
3. **Runnable README blocks (offline, simulator):**
   - `RXKARABO_SIM=1 uv run python examples/read_property.py <dev> <prop>` → prints one value.
   - `RXKARABO_SIM=1 uv run python examples/poll_property.py <dev> <prop> 500` → streaming values.
   - `RXKARABO_SIM=1 uv run python examples/monitor_property.py <dev> <prop>` → push updates.
   - `RXKARABO_SIM=1 uv run python examples/pipeline.py` → read→calibrate→write→read-back.
   Confirm each prints a sensible stream and exits cleanly (Ctrl-C for the infinite ones).
4. **Package import without Karabo:** `uv run python -c "import rxkarabo"` succeeds (lazy
   middlelayer import not triggered).
5. **Slides:** open `docs/rxkarabo-talk/index.html` in a browser; arrow-key navigation,
   syntax highlighting, progress bar, and the cross-link card all work.
