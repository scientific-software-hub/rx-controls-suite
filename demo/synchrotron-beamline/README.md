# Synchrotron Beamline — Combined Reactive Demo

One Python process. Two control systems. One declarative pipeline.

```
  Storage Ring (Tango/C++)          Tomography Beamline (EPICS)
  ─────────────────────────         ──────────────────────────────
  sr/demo/controller                TOMO:ROT:VAL / TOMO:ROT:MOVN
    BeamCurrent   → gate/shutter    TOMO:DET:ACQUIRE / COUNTS
    InterlockCount → abort          TOMO:BEAM:POSX / POSY
  sr/demo/sector04                  TOMO:SHUTTER:OPEN
    OrbitX        → quality flag    TOMO:SCAN:STATUS

                    one rx.zip
                  ┌──────────────────────────────────────┐
                  │  rx.zip(                             │
                  │    read_pv(COUNTS),          # EPICS │
                  │    read_pv(BEAM_POSX),       # EPICS │
                  │    read_pv(BEAM_POSY),       # EPICS │
                  │    read_attribute(CURRENT),  # Tango │
                  │    read_attribute(ORBIT_X),  # Tango │
                  │  )                                   │
                  └──────────────────────────────────────┘
```

## Reactive patterns demonstrated

| Pattern | Operator(s) | Scenario |
|---------|------------|---------|
| Beam-loss recovery | `filter + take(1) + ignore_elements` | scan pauses when current drops; resumes automatically |
| Shutter supervisor | `map + distinct_until_changed + flat_map` | shutter closes/opens on beam state transitions |
| Orbit-drift quality | `rx.zip` (cross-system) | every frame tagged with Tango orbit_x at acquisition time |
| Vacuum-burst abort | `take_until` | interlock alarm terminates the scan cleanly |
| Backpressure | `share() + sample()` | HDF5 keeps every frame; display drops under load |

## Quickstart

```bash
# 1. Bring up both stacks (builds the C++ ring server on first run)
docker compose up -d --build
docker compose ps     # wait until storage-ring-sim is healthy

# 2. Install the reactive wrappers (one-time)
cd /path/to/rx-controls-suite
uv pip install -e RxTango/python -e RxEpics/python

# 3. Point EPICS Channel Access at the host-networked IOC (every shell)
#    The IOC runs in network_mode: host; without this, CA search only hits
#    the global broadcast (255.255.255.255) and PVs time out.
export EPICS_CA_AUTO_ADDR_LIST=NO
export EPICS_CA_ADDR_LIST=127.0.0.1

# 4. (Terminal A) Monitor the ring
cd demo/synchrotron-beamline
python ring_health.py

# 5. (Terminal B) Run the guarded scan
python guarded_scan.py --ascii

# 6. (Terminal C) Inject faults during the scan
python inject_fault.py beam_loss      # scan pauses, shutter closes
python inject_fault.py nominal        # scan resumes, shutter opens
python inject_fault.py orbit_drift    # quality flags appear on frames
python inject_fault.py nominal        # clear orbit fault
python inject_fault.py vacuum_burst   # emergency abort
```

## Scripts

| Script | What it shows |
|--------|--------------|
| `ring_health.py` | Live ring-health stream (intro) — current, interlocks, orbit |
| `inject_fault.py <scenario>` | Set ring scenario: `nominal \| orbit_drift \| vacuum_burst \| beam_loss` |
| `guarded_scan.py` ★ | **Hero** — full guarded tomography scan fusing Tango + EPICS |

## Presentation

See [`docs/combined-demo-talk/`](../../docs/combined-demo-talk/) for the accompanying
slide deck explaining each operator choice in depth.

## Architecture

```
ring_health (shared, 1 Hz Tango poll)
        │
        ├─ shutter supervisor  →  distinct_until_changed → write_pv(SHUTTER)
        │
        └─ abort_trigger       →  filter(interlocks>0) + take(1)
                                          │
                                     take_until
                                          │
scan = rx.concat(                         │
    setup,                                │
    [wait_healthy → acquire] × N,   ←────┘
    teardown
).pipe(share())
    ├─ HDF5 writer     (every frame)
    └─ live display    (sample(display_ms))
```

## Fault scenarios

### Beam-loss recovery (`python inject_fault.py beam_loss`)

Beam current drops below 50 mA (floor ~25 mA).  The shutter supervisor
writes `TOMO:SHUTTER:OPEN = 0` via `distinct_until_changed`.  The next
projection's `wait_healthy` gate blocks on `health.pipe(filter(is_healthy),
take(1))`.  Inject `nominal` to watch the scan resume automatically.

### Orbit-drift quality flagging (`python inject_fault.py orbit_drift`)

The ring simulator adds drift to orbit_x; sector04 OrbitX exceeds 55 µm.
Every frame's cross-system zip reads OrbitX from Tango at acquisition time.
Frames acquired during drift are marked `quality_ok = False` in the HDF5
dataset and flagged in the live display.

### Vacuum-burst abort (`python inject_fault.py vacuum_burst`)

A vacuum event triggers the interlock fan-in in the C++ simulator
(`InterlockCount > 0`).  The `abort_trigger` observable emits once;
`take_until` terminates the scan.  An emergency teardown writes
`TOMO:SCAN:STATUS = ABORTED` and closes the shutter.

### Backpressure (always active)

The scan source is `share()`'d.  The HDF5 writer subscribes directly and
receives every frame.  The live display subscribes through `sample(250 ms)`,
which silently drops intermediate frames when the display is slower than
the acquisition — one operator, explicit overload policy.

## Dependencies

Both stacks already use host networking; no port conflicts exist:
- Tango: `localhost:10000` (DatabaseDS)
- EPICS CA: `localhost:5064/5065` — because the IOC is host-networked, every
  client shell must set `EPICS_CA_AUTO_ADDR_LIST=NO` and
  `EPICS_CA_ADDR_LIST=127.0.0.1` (see Quickstart step 3), otherwise CA search
  falls back to the `255.255.255.255` broadcast and PVs fail to connect.
