"""Device simulator — animates the softIoc PVs with realistic behaviour.

Simulates:
  - Rotation stage: finite-velocity motion, RBV tracks VAL at SPEED rate
  - Detector: exposure timing with Poisson-distributed counts
  - Shutter: mirrors OPEN → OPEN:STS

Beam diagnostics are already animated by calc records in the .db file.

Runs until interrupted. Connects to the softIoc via CA on localhost.
"""
from __future__ import annotations

import math
import os
import random
import sys
import time


def _env(key: str, default: str) -> str:
    return os.environ.get(key, default)


# ---------------------------------------------------------------------------
# Caproto threading client
# ---------------------------------------------------------------------------

from caproto.threading.client import Context as CaContext  # noqa: E402

ctx = CaContext()

# Cache PV handles so we don't re-search each loop iteration
PVS: dict[str, "PV"] = {}


def _read(name: str):
    if name not in PVS:
        PVS[name], = ctx.get_pvs(name, timeout=float(_env("CA_TIMEOUT", "5")))
    return PVS[name].read().data[0]


def _write(name: str, value):
    if name not in PVS:
        PVS[name], = ctx.get_pvs(name, timeout=float(_env("CA_TIMEOUT", "5")))
    PVS[name].write([value])


# ---------------------------------------------------------------------------
# Simulation state
# ---------------------------------------------------------------------------

_motor_last_t = time.monotonic()
_det_acquiring = False
_det_start_t = 0.0


def _simulate_counts(exposure_ms: float) -> float:
    """Poisson-like detector counts, base ~10000 per 100 ms exposure."""
    base = 10000.0 * (exposure_ms / 100.0)
    noise = random.gauss(0, math.sqrt(base)) if base > 0 else 0.0
    return max(0.0, base + noise)


def tick() -> None:
    """One simulation step — call at ~10 Hz."""
    global _motor_last_t, _det_acquiring, _det_start_t

    now = time.monotonic()
    dt = now - _motor_last_t
    _motor_last_t = now

    # --- Rotation stage ---
    val = float(_read("TOMO:ROT:VAL"))
    rbv = float(_read("TOMO:ROT:RBV"))
    spd = float(_read("TOMO:ROT:SPEED"))

    if abs(val - rbv) < 0.0005:
        _write("TOMO:ROT:RBV", val)
        _write("TOMO:ROT:MOVN", 0)
    else:
        step = spd * dt
        direction = 1.0 if val > rbv else -1.0
        new_rbv = rbv + direction * min(step, abs(val - rbv))
        _write("TOMO:ROT:RBV", new_rbv)
        _write("TOMO:ROT:MOVN", 1)

    # --- Detector ---
    acquire = int(_read("TOMO:DET:ACQUIRE"))
    if acquire and not _det_acquiring:
        _det_acquiring = True
        _det_start_t = now
        _write("TOMO:DET:ACQUIRING", 1)
        _write("TOMO:DET:ACQUIRE", 0)  # consume trigger

    if _det_acquiring:
        exposure_ms = float(_read("TOMO:DET:EXPOSURE"))
        elapsed_ms = (now - _det_start_t) * 1000.0
        if elapsed_ms >= exposure_ms:
            counts = _simulate_counts(exposure_ms)
            _write("TOMO:DET:COUNTS", counts)
            _write("TOMO:DET:ACQUIRING", 0)
            _det_acquiring = False

    # --- Shutter ---
    open_val = int(_read("TOMO:SHUTTER:OPEN"))
    _write("TOMO:SHUTTER:OPEN:STS", open_val)


# ---------------------------------------------------------------------------
# Main loop
# ---------------------------------------------------------------------------

def main() -> None:
    tick_rate = float(_env("SIM_TICK_RATE", "0.1"))  # seconds
    timeout_s = float(_env("CA_TIMEOUT", "10"))

    # Pre-connect to all PVs so the first tick doesn't stall
    pv_names = [
        "TOMO:ROT:VAL",
        "TOMO:ROT:RBV",
        "TOMO:ROT:SPEED",
        "TOMO:ROT:MOVN",
        "TOMO:DET:EXPOSURE",
        "TOMO:DET:ACQUIRE",
        "TOMO:DET:COUNTS",
        "TOMO:DET:ACQUIRING",
        "TOMO:SHUTTER:OPEN",
        "TOMO:SHUTTER:OPEN:STS",
    ]
    print(f"Connecting to {len(pv_names)} PVs ...", file=sys.stderr)
    for name in pv_names:
        PVS[name], = ctx.get_pvs(name, timeout=timeout_s)
    print("Simulator running. Ctrl-C to stop.", file=sys.stderr)

    while True:
        try:
            tick()
        except Exception as exc:
            print(f"tick error: {exc}", file=sys.stderr)
        time.sleep(tick_rate)


if __name__ == "__main__":
    main()
