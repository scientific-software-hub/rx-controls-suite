"""Bluesky-protocol devices built from rx-controls-suite pipelines.

No ophyd, no pyepics — each device implements the Bluesky protocols
(Readable / Movable / Triggerable) directly, and every verb is an rx
pipeline from rxepics/rxtango:

    motor.set(angle)   →  RxStatus( write_pv(ROT:VAL) → poll MOVN == 0 )
    detector.trigger() →  RxStatus( write_pv(ACQUIRE) → poll ACQUIRING 1→0 )
    ring.read()        →  rx_wait( rx.zip(3 × Tango read_attribute) )

RingHealth is the cross-system star: it is an ordinary Bluesky Readable,
so ``bp.scan([detector, ring], motor, ...)`` lands EPICS counts and Tango
ring state in the *same Event document* — the pure-rx demo's cross-system
zip, re-expressed in Bluesky vocabulary.
"""

import sys
import time
from pathlib import Path

import reactivex as rx
import reactivex.operators as ops

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from facility import (  # noqa: E402
    CONTROLLER, SECTOR_04, ORBIT_ALARM,
    PV_ROT_VAL, PV_ROT_MOVN,
    PV_DET_ACQUIRE, PV_DET_COUNTS, PV_DET_ACQUIRING,
    PV_BEAM_POSX, PV_BEAM_POSY,
    poll_until,
)
from rx_bluesky import RxLoop, RxStatus, rx_wait  # noqa: E402
from rxepics.channel import read_pv  # noqa: E402
from rxepics.channel_write import write_pv  # noqa: E402
from rxtango import read_attribute  # noqa: E402


def _reading(value):
    return {"value": value, "timestamp": time.time()}


class _RxDevice:
    """Shared Bluesky-protocol scaffolding for the rx-backed devices."""

    parent = None

    def __init__(self, name: str, ctx, rx_loop: RxLoop):
        self.name = name
        self._ctx = ctx
        self._rx = rx_loop

    def read_configuration(self):
        return {}

    def describe_configuration(self):
        return {}

    def stop(self, *, success: bool = False) -> None:
        pass


class PVDevice(_RxDevice):
    """A single settable + readable PV (shutter, motor speed, exposure).

    ``set()`` completes when the write pipeline completes — for these soft
    PVs that is immediate, but the Status contract is identical to the
    motor's, so plans treat them uniformly (``bps.mv(shutter, 1)``).
    """

    def __init__(self, name: str, pv: str, ctx, rx_loop: RxLoop):
        super().__init__(name, ctx, rx_loop)
        self._pv = pv

    def set(self, value) -> RxStatus:
        return RxStatus(write_pv(self._pv, value, self._ctx), self._rx)

    def read(self):
        return {self.name: _reading(rx_wait(read_pv(self._pv, self._ctx), self._rx))}

    def describe(self):
        return {self.name: {"source": f"ca://{self._pv}", "dtype": "number", "shape": []}}

    @property
    def hints(self):
        return {"fields": [self.name]}


class RotationMotor(_RxDevice):
    """The tomography rotation stage as a Bluesky Movable + Readable.

    set() returns an RxStatus over the same pipeline the pure-rx demo uses:
    write ROT:VAL, then poll ROT:MOVN every 10 ms until the axis stops.
    """

    def set(self, angle: float) -> RxStatus:
        pipeline = write_pv(PV_ROT_VAL, float(angle), self._ctx).pipe(
            ops.flat_map(lambda _: poll_until(
                PV_ROT_MOVN, lambda v: v == 0, 10, self._ctx, self._rx.scheduler,
            )),
        )
        return RxStatus(pipeline, self._rx)

    def read(self):
        return {"angle": _reading(rx_wait(read_pv(PV_ROT_VAL, self._ctx), self._rx))}

    def describe(self):
        return {"angle": {"source": f"ca://{PV_ROT_VAL}", "dtype": "number", "shape": []}}

    @property
    def hints(self):
        return {"fields": ["angle"]}


class TomoDetector(_RxDevice):
    """The tomography detector as a Bluesky Triggerable + Readable.

    trigger() arms the acquisition and completes when ACQUIRING falls back
    to 0; read() zips counts and beam position in one parallel snapshot.
    """

    def trigger(self) -> RxStatus:
        pipeline = write_pv(PV_DET_ACQUIRE, 1, self._ctx).pipe(
            ops.flat_map(lambda _: poll_until(
                PV_DET_ACQUIRING, lambda v: v == 1, 5, self._ctx, self._rx.scheduler,
            )),
            ops.flat_map(lambda _: poll_until(
                PV_DET_ACQUIRING, lambda v: v == 0, 5, self._ctx, self._rx.scheduler,
            )),
        )
        return RxStatus(pipeline, self._rx)

    def read(self):
        counts, posx, posy = rx_wait(rx.zip(
            read_pv(PV_DET_COUNTS, self._ctx),
            read_pv(PV_BEAM_POSX, self._ctx),
            read_pv(PV_BEAM_POSY, self._ctx),
        ), self._rx)
        return {
            "counts":    _reading(float(counts)),
            "beam_posx": _reading(float(posx)),
            "beam_posy": _reading(float(posy)),
        }

    def describe(self):
        return {
            "counts":    {"source": f"ca://{PV_DET_COUNTS}", "dtype": "number", "shape": []},
            "beam_posx": {"source": f"ca://{PV_BEAM_POSX}", "dtype": "number", "shape": []},
            "beam_posy": {"source": f"ca://{PV_BEAM_POSY}", "dtype": "number", "shape": []},
        }

    @property
    def hints(self):
        return {"fields": ["counts"]}


class RingHealth(_RxDevice):
    """The Tango storage ring as a Bluesky Readable.

    Listing this device among the detectors of a plan puts Tango ring state
    into every Event document, acquired in parallel with the EPICS reads —
    including the derived per-frame quality flag from the orbit reading.
    """

    def read(self):
        current, interlocks, orbit_x = rx_wait(rx.zip(
            read_attribute(CONTROLLER, "BeamCurrent"),
            read_attribute(CONTROLLER, "InterlockCount"),
            read_attribute(SECTOR_04, "OrbitX"),
        ), self._rx)
        return {
            "ring_current": _reading(float(current)),
            "interlocks":   _reading(int(interlocks)),
            "orbit_x":      _reading(float(orbit_x)),
            "quality_ok":   _reading(bool(abs(float(orbit_x)) < ORBIT_ALARM)),
        }

    def describe(self):
        return {
            "ring_current": {"source": f"tango://{CONTROLLER}/BeamCurrent", "dtype": "number", "shape": []},
            "interlocks":   {"source": f"tango://{CONTROLLER}/InterlockCount", "dtype": "integer", "shape": []},
            "orbit_x":      {"source": f"tango://{SECTOR_04}/OrbitX", "dtype": "number", "shape": []},
            "quality_ok":   {"source": "derived: |orbit_x| < ORBIT_ALARM", "dtype": "boolean", "shape": []},
        }

    @property
    def hints(self):
        return {"fields": ["ring_current", "orbit_x"]}
