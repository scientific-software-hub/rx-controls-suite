# RxDECTRIS integration demo

> DECTRIS already provides portable detector and cloud APIs. This demo shows
> that the experiment orchestration *around* those APIs can be portable too.

The existing [`demo/synchrotron-beamline`](../synchrotron-beamline/) proves
the suite's abstraction works — Tango ring × EPICS beamline, one reactive
experiment. This demo makes the same point in DECTRIS's own vocabulary: the
detector lifecycle is a (simulated) DECTRIS detector talking SIMPLON, the
processing stage is a D.LAB-shaped job API, and the reveal is that swapping
the facility control system underneath leaves the experiment recipe
untouched.

## Architecture

```
                         SAME EXPERIMENT RECIPE
                                  │
                  ┌───────────────┴───────────────┐
             EpicsFacility                  TangoFacility
             (rxepics, via                  (rxtango, direct —
              facility_bridge.py)            same simulated ring)
                  └───────────────┬───────────────┘
                          Observable[FacilityHealth]
                                  │
                             RxDectris (SIMPLON)
                        ┌─────────┴─────────┐
                  SIMPLON REST         Stream V2 (ZMQ/CBOR)
                        └─────────┬─────────┘
                            simplon_sim
                                  │
                     HDF5 (AcquisitionRun) ──► RxDlab
                                                  │
                                              dlab_sim
```

Both facility adapters observe **the same simulated storage ring**
(`demo/synchrotron-beamline`'s Tango C++ server) through two different
control systems — `TangoFacility` reads it directly;
`EpicsFacility`/`facility_bridge.py` mirror it into EPICS PVs so an
EPICS-only client sees it too. That's deliberate: it's what makes an
`epics` run and a `tango` run a fair, provable comparison, not two demos
wearing the same recipe.

## Files

| File | Role |
|---|---|
| `simplon_sim/` | SIMPLON-shaped detector simulator — FastAPI HTTP + a real Stream V2 ZeroMQ/CBOR socket |
| `dlab_sim/` | Conceptual D.LAB-shaped mock — Projects/Datasets/Jobs (see caveat below) |
| `facilities.py` | `FacilityHealth`, the `Facility` protocol, `TangoFacility`/`EpicsFacility`/`FakeFacility` |
| `facility_bridge.py` | Mirrors the Tango ring into EPICS `FAC:*` PVs for `EpicsFacility` |
| `dlab.py` | `RxDlab` — upload / run_job / await_result as `rx.Observable`s |
| `recipes.py` | The reusable vocabulary: `wait_until_healthy`, `guarded_by`, `correlate_with`, `process_with`, `validate_result`, `AcquisitionRun` |
| `experiment.py` | The hero pipeline — `--facility epics\|tango` |
| `inject_fault.py` | One command for all four fault families |
| `dashboard.py` + `index.html` | Live FACILITY / DETECTOR / D.LAB status page, `:8020` |
| `tests/` | Mock-only unit tests — no stack, no network |

`RxDectris/python/` (sibling to `RxTango/python` and `RxEpics/python`) is
the actual reusable SIMPLON wrapper this demo is built on — see
[its README](../../RxDectris/python/README.md) for the library API, the
SIMPLON-endpoint-to-function mapping, and exactly what parts of the
simulator are faithful to the public SIMPLON API documentation versus
simplified for the demo.

## Run book

```bash
# 1. Stack: storage ring (Tango) + tomography beamline (EPICS) + SIMPLON sim + D.LAB mock
cd demo/dectris-integration
docker compose up -d --build
docker compose ps   # wait for storage-ring-sim-server healthy

# 2. One-time: editable-install the wrapper packages
uv pip install -e ../../RxTango/python -e ../../RxEpics/python -e ../../RxDectris/python

# 3. Every client shell (the IOC is host-networked)
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1

# 4. For an --facility epics run, mirror the Tango ring into EPICS first:
python facility_bridge.py &

# 5. The hero pipeline
python experiment.py --facility tango --frames 100 --count-time 0.01
python experiment.py --facility epics --frames 100 --count-time 0.01

# 6. Faults, any time, in another shell
python inject_fault.py beam_loss          # Scenario A — gate holds, recovers
python inject_fault.py vacuum_burst       # Scenario B — interlock aborts cleanly
python inject_fault.py detector_error     # Scenario C — trigger fails, teardown runs
python inject_fault.py flaky_processing   # Scenario D — D.LAB retries, detector NOT re-triggered
python inject_fault.py nominal            # reset ring + detector + D.LAB

# 7. Dashboard (own terminal)
uv run --with fastapi --with "uvicorn[standard]" python dashboard.py
# -> http://localhost:8020
```

Ports: `8080` SIMPLON HTTP, `31001` Stream V2, `8090` D.LAB mock, `8020`
dashboard. (`8000`, `8010`, `4200` are already used by the other demos in
this repo.)

If Tango reports `API_DeviceNotExported` after a stack restart:
`docker restart storage-ring-sim-server` (it needs to re-register with the
DB — see the synchrotron-beamline demo's own README for the full story).

## Tests

```bash
pytest RxDectris/python/tests -q       # the wrapper — no simulator needed
pytest demo/dectris-integration/tests -q   # this demo — no stack needed
```

Both suites run against hand-written fakes (`httpx.MockTransport` for REST,
an in-memory queue for the Stream V2 socket) — nothing here requires the
docker stack.

## What this demo does and does not claim

**Does:** demonstrate that one experiment recipe — gate on facility health,
acquire a detector series, correlate every frame with facility state,
upload and process the result, retry the processing stage without
re-triggering the detector — survives swapping the underlying facility
control system between Tango and EPICS.

**Does not claim:**

- That `simplon_sim` is a faithful reproduction of every DECTRIS detector
  generation. It's built against one documented lifecycle (SIMPLON 1.8) for
  one representative sequence — see `RxDectris/python/README.md`'s "what is
  simulated" table for the exact list of simplifications.
- That the D.LAB mock reproduces the real D.LAB API. **No public D.LAB
  endpoint specification exists** — `dlab.py`/`dlab_sim/` model only the
  public *concepts* (Projects, Datasets, Jobs), not real endpoints.
- That `rx-controls-suite` currently supports DOOCS, Karabo, or BLISS. The
  correct claim is narrower: the same adapter model (a `Facility`/detector
  wrapper exposing `Observable`s, composed with reusable recipes) could be
  implemented for them — not that it has been.

## The two objections worth having answers ready for

**"We already have portable HTTP APIs — why introduce another
abstraction?"** The proposal isn't to abstract SIMPLON. REST already
handles "arm this detector." It doesn't answer *when* arm should happen,
what cancels it, what has to be correlated with every frame, which
consumers can drop data, or what must retry without repeating what came
before. Those are workflow semantics — SIMPLON's own Monitor subsystem
(`/images/next` vs `/images/monitor`, one API-documented endpoint explicitly
for "don't use above 10 Hz") is DECTRIS's own product already expressing
half of this problem.

**"This looks like a state machine."** Parts of it are, and that's fine —
reactive composition isn't automatically superior. The question worth
testing in a workshop is whether the specific mix of async streams,
fan-in/fan-out, cancellation, and cross-system correlation in a real
DECTRIS integration is dense enough that composing it through streams reads
clearer than hand-rolled callbacks. The workshop is explicitly allowed to
conclude it isn't.

See [`demo-script.md`](demo-script.md) for the exact meeting sequence.
