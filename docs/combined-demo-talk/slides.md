# Reactive Programming Across Control Systems
## Storage Ring × Tomography Beamline

**Igor Khokhriakov**
Principal Software Engineer · Hamburg

> One Python process · Two control systems · One declarative pipeline

---

# Slide 1 — Title

## Reactive Programming Across Control Systems
### Storage Ring × Tomography Beamline

*One Python process. Two control systems. One reactive pipeline.*

**github.com/scientific-software-hub/rx-controls-suite**

---
Speaker notes:
This talk is the capstone of the rx-controls-suite series.
We've shown Tango (Java), EPICS (Python), Tango (Python) separately.
Now: what happens when you connect them? A storage ring feeding a beamline.
One process, two control systems, one reactive pipeline.

---

# Slide 2 — The Facility

## A real problem: two control systems, one experiment

```
  Storage Ring              →  Beamline
  ─────────────────────           ──────────────────────────
  Tango Controls (C++)            EPICS Channel Access
  sr/demo/controller              TOMO:ROT:VAL / MOVN
    BeamCurrent   ← the source    TOMO:DET:ACQUIRE / COUNTS
    InterlockCount                TOMO:BEAM:POSX / POSY
  sr/demo/sector04                TOMO:SHUTTER:OPEN
    OrbitX        ← quality       TOMO:SCAN:STATUS
```

A tomography scan acquires 360 projections.
The quality of each projection depends on the ring state at acquisition time.
A ring fault mid-scan demands an immediate reaction — shutter, pause, or abort.

Today: polling loops, shared flags, callbacks, threading.Lock.
With Rx: operators.

---
Speaker notes:
This is the real scenario at any synchrotron facility.
The ring and the beamline run separate control systems (Tango, EPICS, DOOCS, TINE...).
A beamline scientist needs to react to ring state in real time, from Python.
We want to show that reactive operators handle this cleanly.

---

# Slide 3 — The Cross-System Zip

## One operator. Two control systems. Fired in parallel.

The showstopper. This fires on every projection:

```python
# At the moment detector exposure completes:
ops.flat_map(lambda _: rx.zip(

    read_pv("TOMO:DET:COUNTS",  ctx),     # EPICS → caproto CA
    read_pv("TOMO:BEAM:POSX",   ctx),     # EPICS → caproto CA
    read_pv("TOMO:BEAM:POSY",   ctx),     # EPICS → caproto CA

    read_attribute(CONTROLLER, "BeamCurrent"),  # Tango → PyTango
    read_attribute(SECTOR_04,  "OrbitX"),       # Tango → PyTango

)),
ops.map(lambda r: (
    r[0], r[1], r[2],            # EPICS data
    r[3], r[4],                  # Tango data
    abs(r[4]) < ORBIT_ALARM,     # quality flag ← from Tango orbit
))
```

All five requests are in-flight simultaneously.
The tuple is emitted only when all five complete.
If any fails, the frame is dropped — never half-written.

---
Speaker notes:
This is the "aha" moment. The audience expects a two-step process: read EPICS, then read Tango.
Instead: rx.zip sends all five requests at once and waits for all five to complete.
Same operator they've seen for multi-device Tango reads or multi-PV EPICS reads.
One new import. Zero new concepts.

---

# Slide 4 — Ring Health as a Stream

## The ring state is just another Observable

```python
# facility.py — the shared ring-health stream
def ring_health(scheduler, interval_ms=1000) -> rx.Observable:
    return rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(

        # Read BeamCurrent, InterlockCount, OrbitX simultaneously
        ops.flat_map(lambda _: rx.zip(
            read_attribute(CONTROLLER, "BeamCurrent"),
            read_attribute(CONTROLLER, "InterlockCount"),
            read_attribute(SECTOR_04,  "OrbitX"),
        )),

        ops.map(lambda t: Health(
            current=float(t[0]),
            interlocks=int(t[1]),
            orbit_x=float(t[2]),
        )),

        ops.share(),  # one poll → many subscribers (shutter, abort, gate)
    )
```

`share()` is the key: a single polling subscription, multiple observers.
No duplicate network traffic. Deterministic timing.

---
Speaker notes:
share() here is doing something powerful: it turns one poll stream into a broadcast.
Three subscribers (shutter supervisor, abort trigger, per-projection gate) all see the same events.
Only one TCP connection to the Tango server per interval tick.

---

# Slide 5 — Pattern 1: Beam-Loss Recovery

## The scan gates itself on ring health

```python
# Before each projection: wait for healthy beam
wait_healthy = health.pipe(
    ops.filter(is_healthy),    # current >= 50 mA AND interlocks == 0
    ops.take(1),               # complete after first passing emission
    ops.ignore_elements(),     # discard value — we only need the timing
)

# Shutter supervisor — runs in parallel throughout the scan
supervisor = health.pipe(
    ops.map(lambda h: h.current >= MIN_BEAM_CURRENT),
    ops.distinct_until_changed(),                 # only on state transitions
    ops.flat_map(lambda ok:
        write_pv("TOMO:SHUTTER:OPEN", 1 if ok else 0, ctx)
    ),
)

# Each guarded projection: wait → then acquire
return rx.concat(wait_healthy, acquire_projection(...))
```

```bash
python inject_fault.py beam_loss   # current → 25 mA; shutter closes; scan pauses
python inject_fault.py nominal     # current → 100 mA; shutter opens; scan resumes
```

No polling loop. No threading.Event. No flag variable.
Three operators. Automatic.

---
Speaker notes:
The audience should feel the contrast: without Rx this is ~50 lines of threading code.
With Rx: filter + take(1) + distinct_until_changed.
Notice that the scan never explicitly "pauses" — it just stops starting new projections.
The rx.concat ensures sequential execution; the gate is just waiting for the next healthy tick.

---

# Slide 6 — Pattern 2: Orbit-Drift Quality Flagging

## Every frame carries its own quality certificate

```python
# Inside guarded_acquire_projection — the cross-system zip step:
ops.map(lambda r: (
    time.time(), index, angle,
    float(r[0]),                  # counts       [EPICS]
    float(r[1]),                  # beam_posx    [EPICS]
    float(r[2]),                  # beam_posy    [EPICS]
    float(r[3]),                  # ring_current [Tango]
    float(r[4]),                  # orbit_x      [Tango]
    abs(float(r[4])) < 55.0,      # quality_ok ← Tango orbit at acquisition time
))
```

```python
# HDF5 dataset dtype includes quality_ok per frame
dtype=np.dtype([
    ("counts",       "f8"),
    ("ring_current", "f4"),   # from Tango
    ("orbit_x",      "f4"),   # from Tango
    ("quality_ok",   "?"),    # True/False per frame
])
```

```bash
python inject_fault.py orbit_drift  # orbit_x exceeds 55 µm; frames marked False
```

---
Speaker notes:
In the traditional approach you'd either:
(a) read the ring separately and correlate timestamps post-hoc, or
(b) have a background thread that writes ring state to a shared buffer.
With rx.zip, the ring state is co-acquired with the detector data in the same atomic operation.
The quality flag is computed at the same instant as the acquisition. No correlation needed.

---

# Slide 7 — Pattern 3: Vacuum-Burst Abort

## take_until: one operator terminates the entire pipeline

```python
# Abort trigger: fires once when any interlock appears
abort_trigger = health.pipe(
    ops.filter(lambda h: h.interlocks > 0),
    ops.take(1),
    ops.do_action(on_next=lambda h: print(
        f"⚠  VACUUM BURST: interlocks={h.interlocks} — emergency abort!"
    )),
)

# Apply to the entire scan
scan = rx.concat(setup, *projections, teardown).pipe(
    ops.take_until(abort_trigger)
)

# After scan completes — check for abort and do emergency teardown
if scan_aborted.is_set():
    rx.zip(
        write_pv("TOMO:SCAN:STATUS", SCAN_ABORTED, ctx),
        write_pv("TOMO:SHUTTER:OPEN", 0, ctx),
    ).subscribe(...)
```

```bash
python inject_fault.py vacuum_burst   # interlocks → 1; scan terminates
```

No try/except. No thread flags. One operator wraps the entire multi-projection scan.

---
Speaker notes:
take_until is the most dramatic demo.
The entire rx.concat chain — which is potentially 360 sequential projections — 
is cancelled by a single emission from abort_trigger.
This is the composability of Rx: you can wrap an arbitrarily complex pipeline
with one operator and change its termination semantics completely.

---

# Slide 8 — Pattern 4: Backpressure

## share() + sample(): one operator, explicit overload policy

```python
# One execution of the scan — two consumers
source = scan.pipe(ops.share())

# HDF5 writer: receives every frame — must keep up
source.subscribe(on_next=write_frame, scheduler=scheduler)

# Live display: throttled — drops frames silently when slow
source.pipe(
    ops.sample(timedelta(milliseconds=250), scheduler=scheduler),
).subscribe(on_next=display_frame, scheduler=scheduler)
```

No queues. No thread locks. No manual drop counters.
`sample()` keeps the most recent value in each time window.
The slow consumer never backpressures the fast producer.

The application explicitly chooses the overload strategy —
here: "drop intermediate frames; HDF5 is the ground truth."

---
Speaker notes:
This is the same pattern as the EPICS tomography demo.
The key insight: once you express the scan as an Observable, backpressure
is just another operator. You don't redesign the scan — you add one line.
Contrast with a traditional approach: you'd need a thread, a queue, a conditional write loop.

---

# Slide 9 — The Guarded Scan — Full Pipeline

## All four patterns in one readable declaration

```python
# Four behaviours. Five operators. One pipeline.

health = ring_health(scheduler)           # shared, 1 Hz

supervisor = health.pipe(                  # PATTERN 4: shutter
    ops.map(lambda h: h.current >= 50.0),
    ops.distinct_until_changed(),
    ops.flat_map(lambda ok: write_pv(SHUTTER, 1 if ok else 0, ctx)),
).subscribe(...)

abort = health.pipe(                       # PATTERN 3: abort
    ops.filter(lambda h: h.interlocks > 0),
    ops.take(1),
)

scan = rx.concat(setup,                    # PATTERN 1: beam-loss gate
    *[rx.concat(wait_healthy, acquire(angle, i, health))  # per projection
      for i, angle in enumerate(angles)],
    teardown,
).pipe(ops.take_until(abort))             # PATTERN 3 (applied)

source = scan.pipe(ops.share())            # PATTERN 4: backpressure
source.subscribe(on_next=write_frame)      #   — HDF5 every frame
source.pipe(ops.sample(250ms)).subscribe(  #   — display throttled
    on_next=display_frame)
```

---
Speaker notes:
This is the slide to linger on. Walk through it top to bottom.
Each line corresponds to a real requirement from a beamline scientist.
The total scan logic — including cross-system fault handling — is about 60 lines of Python.
The equivalent threading-based implementation would be 300–400 lines.
And each new requirement would add MORE complexity, not more operators.

---

# Slide 10 — Live Demo

## Two terminals. One facility.

```bash
# Terminal A — start the full stack
docker compose up -d --build

# Terminal B — ring health monitor (shows ring state live)
python ring_health.py

# Terminal C — guarded scan (the hero)
python guarded_scan.py --ascii

# Terminal D — inject faults
python inject_fault.py beam_loss      # pause + shutter close
python inject_fault.py nominal        # resume + shutter open
python inject_fault.py orbit_drift    # quality flags appear
python inject_fault.py vacuum_burst   # emergency abort
```

HDF5 output includes `ring_current`, `orbit_x`, and `quality_ok` per frame.

---
Speaker notes:
The demo flow:
1. Start scan — show it running in ascii mode, projections incrementing.
2. Inject beam_loss — shutter closes, scan pauses visibly (no new projections).
3. Inject nominal — shutter opens, scan resumes from where it left off.
4. Inject orbit_drift — show ~ quality flags appearing in the table.
5. Inject nominal — flags clear.
6. Inject vacuum_burst — emergency abort, status = ABORTED.
Keep it fast: 4 faults, each takes 10 seconds.

---

# Slide 11 — What We Learned

## Same operators. Any control system.

| Rx operator | What it solved |
|---|---|
| `rx.zip` | Parallel reads across EPICS + Tango — atomic frame |
| `share()` | One ring-health poll, three subscribers, no duplication |
| `filter + take(1)` | Beam-loss gate — blocks acquisition until beam is OK |
| `distinct_until_changed` | Shutter supervisor — fires only on state transitions |
| `take_until` | Vacuum-burst abort — terminates a 360-projection scan in one line |
| `sample()` | Backpressure — display drops; HDF5 keeps all |

Adding a new fault scenario: one `filter + take(1)` + hook into the pipeline.
No shared state. No new threads. No protocol glue code.

**github.com/scientific-software-hub/rx-controls-suite**

---
Speaker notes:
The conclusion to drive home:
The operators don't know — and don't care — which control system is underneath.
rx.zip works the same whether it's zipping EPICS PVs, Tango attributes, or both simultaneously.
The reactive abstraction is the lingua franca across all of them.
If you know the operators, you can connect any combination of control systems.
