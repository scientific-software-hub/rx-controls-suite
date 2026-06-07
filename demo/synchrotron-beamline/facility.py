"""Shared constants, types, and the ring-health Observable for the combined demo.

This module is the Python equivalent of RxTango/demo/lib/RingDevices.java:
a single source of truth for device addresses, PV names, thresholds, and
reactive primitives shared by every script in this demo.

Path bootstrap — adds both reactive wrapper packages to sys.path so the demo
can be run without a global install:

    uv pip install -e ../../RxTango/python -e ../../RxEpics/python

or directly from the repo root via sys.path below.
"""

import sys
from collections import namedtuple
from datetime import timedelta
from pathlib import Path

# ── path bootstrap ────────────────────────────────────────────────────────────
_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(_ROOT / "RxTango" / "python" / "src"))
sys.path.insert(0, str(_ROOT / "RxEpics" / "python" / "src"))

import reactivex as rx
import reactivex.operators as ops

from rxtango import read_attribute

# ── Tango devices ─────────────────────────────────────────────────────────────
CONTROLLER = "tango://localhost:10000/sr/demo/controller"
SECTOR_04  = "tango://localhost:10000/sr/demo/sector04"   # representative sector

# ── EPICS PVs (tomography beamline) ──────────────────────────────────────────
PV_ROT_VAL     = "TOMO:ROT:VAL"
PV_ROT_MOVN    = "TOMO:ROT:MOVN"
PV_ROT_SPEED   = "TOMO:ROT:SPEED"
PV_DET_ACQUIRE = "TOMO:DET:ACQUIRE"
PV_DET_COUNTS  = "TOMO:DET:COUNTS"
PV_DET_ACQUIRING = "TOMO:DET:ACQUIRING"
PV_DET_EXPOSURE  = "TOMO:DET:EXPOSURE"
PV_BEAM_POSX   = "TOMO:BEAM:POSX"
PV_BEAM_POSY   = "TOMO:BEAM:POSY"
PV_SHUTTER     = "TOMO:SHUTTER:OPEN"
PV_SCAN_STATUS = "TOMO:SCAN:STATUS"
PV_SCAN_CUR_ANGLE = "TOMO:SCAN:CUR_ANGLE"
PV_SCAN_CUR_PROJ  = "TOMO:SCAN:CUR_PROJ"

# Scan status values (matches tomography.db mbbi record)
SCAN_IDLE    = 0
SCAN_RUNNING = 1
SCAN_DONE    = 2
SCAN_ABORTED = 3

# ── Thresholds (derived from SimulationEngine.cpp alarm levels) ───────────────
# Nominal beam current is ~100 mA (varies with scenario).
# beam_loss scenario decays to a floor of 25 mA.
# 50 mA is a comfortable mid-point: above loss floor, below nominal.
MIN_BEAM_CURRENT = 50.0   # mA — below this the shutter closes and acquisition gates

# Orbit alarm from SimulationEngine: |orbit| >= 55 µm triggers interlock.
# Frames acquired with |orbit_x| >= this threshold are flagged low-quality.
ORBIT_ALARM = 55.0         # µm

# ── Ring health namedtuple ────────────────────────────────────────────────────
Health = namedtuple("Health", ["current", "interlocks", "orbit_x"])


def is_healthy(h: Health) -> bool:
    """True when the storage ring is safe to acquire into the beamline.

    Requires both sufficient beam current AND no active interlocks.
    Quality (orbit) is tracked separately — bad orbit degrades frame quality
    but does not stop the acquisition.
    """
    return h.current >= MIN_BEAM_CURRENT and h.interlocks == 0


# ── Ring health Observable ────────────────────────────────────────────────────

def ring_health(scheduler, interval_ms: int = 1000) -> rx.Observable:
    """Continuously poll the storage ring and emit a Health snapshot.

    Reads three attributes in parallel on every tick:
      - BeamCurrent    (sr/demo/controller)   — ring-wide beam current [mA]
      - InterlockCount (sr/demo/controller)   — active interlocks (alarm fan-in)
      - OrbitX         (sr/demo/sector04)     — representative orbit deviation [µm]

    Returns a *shared* Observable: all downstream subscribers see the same
    polling stream — no duplicate network traffic, deterministic timing.

    This mirrors the Java dashboard's ``readController()`` + ``readSector()``
    pattern from RingDevices.java, re-expressed in five lines of Rx.
    """
    return rx.interval(timedelta(milliseconds=interval_ms), scheduler=scheduler).pipe(
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
        ops.share(),  # one poll subscription, many observers — key for the demo
    )


# ── Shared reactive primitive ─────────────────────────────────────────────────

def poll_until(pv_name: str, predicate, period_ms: float, ctx, scheduler) -> rx.Observable:
    """Poll *pv_name* every *period_ms* ms until *predicate(value)* is True.

    Emits the first matching value, then completes.
    Pattern: interval → flat_map(read_pv) → filter → take(1).
    """
    from rxepics.channel import read_pv
    return rx.interval(timedelta(milliseconds=period_ms), scheduler=scheduler).pipe(
        ops.flat_map(lambda _: read_pv(pv_name, ctx)),
        ops.filter(predicate),
        ops.take(1),
    )
