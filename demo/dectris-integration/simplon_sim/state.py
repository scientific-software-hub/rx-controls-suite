"""The SIMPLON-shaped state machine, decoupled from FastAPI/HTTP.

Built against the public *SIMPLON 1.8 API documentation, v3.5* (DECTRIS Ltd.,
2025-01-14) — see ``RxDectris/python/README.md``'s "what is simulated / what
is not" table for exactly which parts are faithful and which are simplified.

Key real-hardware behaviours this reproduces on purpose, because the demo's
story depends on them:

- Stream V2 ``start`` is emitted by ``arm`` (not ``trigger``); ``end`` is
  emitted when the series is disarmed — and for internal trigger modes
  (``ints``/``inte``) SIMPLON **auto-disarms** once the triggered series
  completes (documentation footnote to Table 5.5), which is what actually
  emits ``end`` at the end of a normal acquisition. An explicit client
  ``disarm`` afterward is optional and must not error — that's why
  :meth:`DetectorSim.disarm` is lenient about being called from ``idle``.
- ``abort`` drops the pipeline immediately; ``cancel`` finishes the image in
  flight first — genuinely different commands, not aliases.
- A config write can cascade (``count_time`` forcing ``frame_time`` up); the
  PUT response lists every parameter that changed, exactly like the real API.
"""

from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class SimError(Exception):
    """Raised for any illegal request; carries the HTTP status to return."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------------------
# Config parameter table — mirrors SIMPLON 1.8 API documentation §5.1.1
# ---------------------------------------------------------------------------


def _param(value, value_type, unit=None, minimum=None, maximum=None, access_mode="rw"):
    body: dict[str, Any] = {"value": value, "value_type": value_type, "access_mode": access_mode}
    if unit is not None:
        body["unit"] = unit
    if minimum is not None:
        body["min"] = minimum
    if maximum is not None:
        body["max"] = maximum
    return body


def _default_detector_config() -> dict[str, dict]:
    return {
        "count_time": _param(0.1, "float", unit="s", minimum=0.000001, maximum=3600),
        "frame_time": _param(0.1000005, "float", unit="s", minimum=0.000001, maximum=3600),
        "nimages": _param(1, "uint", minimum=1, maximum=1_000_000),
        "ntrigger": _param(1, "uint", minimum=1, maximum=1_000_000),
        "trigger_mode": _param("ints", "string"),
        "incident_energy": _param(12000.0, "float", unit="eV", minimum=1000, maximum=200000),
    }


def _default_stream_config() -> dict[str, dict]:
    return {
        "mode": _param("disabled", "string"),
        "format": _param("legacy", "string"),
        "header_appendix": _param("", "string"),
        "image_appendix": _param("", "string"),
    }


def _default_monitor_config() -> dict[str, dict]:
    return {
        "mode": _param("disabled", "string"),
        "buffer_size": _param(100, "uint", minimum=1, maximum=10_000),
        "discard_new": _param(True, "bool"),
    }


_TRIGGER_MODES = ("ints", "inte", "exts", "exte")


# ---------------------------------------------------------------------------
# The state machine
# ---------------------------------------------------------------------------


@dataclass
class _Series:
    series_id: int
    series_unique_id: str
    number_of_images: int
    count_time: float
    frame_time: float
    ended: bool = False


class DetectorSim:
    """One simulated DCU. HTTP-agnostic: routes in ``app.py`` call these methods.

    *emit* is an async callback ``emit(message: dict)`` that pushes one
    Stream V2 message onto the ZeroMQ socket. *on_monitor_frame* is a sync
    callback that appends a frame dict to the Monitor subsystem buffer.
    """

    def __init__(
        self,
        emit: Callable[[dict], Awaitable[None]],
        on_monitor_frame: Callable[[dict], None],
    ) -> None:
        self.state = "na"
        self.detector_config = _default_detector_config()
        self.stream_config = _default_stream_config()
        self.monitor_config = _default_monitor_config()
        self._emit = emit
        self._on_monitor_frame = on_monitor_frame
        self._sequence = 0
        self._series_counter = 0
        self._current: _Series | None = None
        self._acquire_task: asyncio.Task | None = None
        self._ever_armed = False
        self._fault_pending: str | None = None
        self.progress = {"image_id": -1, "number_of_images": 0}

    # -- helpers ------------------------------------------------------------

    def _next_sequence(self) -> int:
        self._sequence += 1
        return self._sequence

    def _require_state(self, *allowed: str, message: str) -> None:
        if self.state not in allowed:
            raise SimError(message, status_code=409)

    # -- config ---------------------------------------------------------

    def read_config(self, table: dict, parameter: str) -> dict:
        if parameter not in table:
            raise SimError(f"unknown config parameter: {parameter}", status_code=404)
        return table[parameter]

    def write_config(self, table: dict, parameter: str, value: Any) -> list[str]:
        if parameter not in table:
            raise SimError(f"unknown config parameter: {parameter}", status_code=404)
        if table is self.detector_config and parameter == "trigger_mode" and value not in _TRIGGER_MODES:
            raise SimError(f"trigger_mode must be one of {_TRIGGER_MODES}", status_code=400)
        table[parameter]["value"] = value
        changed = [parameter]
        # Reproduce SIMPLON's documented cascade: count_time may force frame_time up.
        if table is self.detector_config and parameter == "count_time":
            frame_time = table["frame_time"]
            if frame_time["value"] < value:
                frame_time["value"] = round(value + 0.0000005, 7)
                changed.append("frame_time")
        return changed

    # -- status -----------------------------------------------------------

    def read_status(self, parameter: str) -> Any:
        if parameter == "state":
            return self.state
        if parameter == "time":
            return time.strftime("%Y-%m-%dT%H:%M:%S")
        if parameter == "error":
            return []  # SIMPLON: always empty; kept for backwards compatibility
        if parameter == "temperature":
            return 22.5
        if parameter == "humidity":
            return 32.0
        if parameter == "high_voltage/state":
            return "READY" if self.state != "na" else "NA"
        raise SimError(f"unknown status parameter: {parameter}", status_code=404)

    # -- commands -----------------------------------------------------------

    async def initialize(self) -> None:
        # Deliberately does NOT clear _fault_pending: an injected fault
        # models a persistent condition that a plain re-initialize
        # shouldn't silently paper over — only an explicit `/_sim/fault
        # {"value": "nominal"}` (inject_fault.py's "nominal") or `abort`
        # (see its own error-state recovery branch) clears it. Every normal
        # acquire_series run calls initialize() unconditionally at startup;
        # if that cleared the fault too, a fault injected before a run would
        # never actually be observed.
        await self._cancel_acquire_task()
        self.state = "idle"
        self._current = None

    async def arm(self) -> int:
        if self.state == "na":
            raise SimError("cannot arm: detector not initialized", status_code=409)
        if self.state in ("ready", "acquire"):
            raise SimError(f"cannot arm: detector already {self.state}", status_code=409)
        # Fault injection fires on trigger, not arm — matches the demo's
        # Scenario C narrative ("trigger -> detector reports error").
        self._series_counter += 1
        series = _Series(
            series_id=self._series_counter,
            series_unique_id=uuid.uuid4().hex,
            number_of_images=int(self.detector_config["nimages"]["value"]),
            count_time=float(self.detector_config["count_time"]["value"]),
            frame_time=float(self.detector_config["frame_time"]["value"]),
        )
        self._current = series
        self._ever_armed = True
        self.state = "ready"
        self.progress = {"image_id": -1, "number_of_images": series.number_of_images}
        await self._emit({
            "type": "start",
            "series_id": series.series_id,
            "series_unique_id": series.series_unique_id,
            "count_time": series.count_time,
            "frame_time": series.frame_time,
            "number_of_images": series.number_of_images,
            "image_size_x": 64,
            "image_size_y": 64,
        })
        return self._next_sequence()

    async def trigger(self, count_time_override: float | None = None) -> None:
        self._require_state("ready", message="cannot trigger: detector not armed")
        if self._fault_pending:
            await self._raise_fault()
        trigger_mode = self.detector_config["trigger_mode"]["value"]
        if not trigger_mode.startswith("int"):
            # External modes are triggered by facility hardware, not this call.
            raise SimError(f"trigger is not valid in trigger_mode={trigger_mode!r}", status_code=409)
        self.state = "acquire"
        assert self._current is not None
        self._acquire_task = asyncio.ensure_future(self._run_series(self._current))

    async def disarm(self) -> int:
        # Lenient: a series in "ints" mode auto-disarms itself when it
        # finishes (see module docstring) — an explicit disarm afterward,
        # while already idle, is a documented no-op rather than an error.
        if self.state == "na":
            raise SimError("cannot disarm: detector not initialized", status_code=409)
        if self.state == "idle" and not self._ever_armed:
            raise SimError("cannot disarm: detector never armed", status_code=409)
        if self.state in ("ready", "acquire"):
            await self._cancel_acquire_task()  # ends the open series (idempotent)
            self.state = "idle"
        # else: already idle — no-op, matches real firmware's tolerance.
        return self._next_sequence()

    async def abort(self) -> int:
        if self.state == "error":
            self.state = "idle"  # simplified recovery: abort clears a fault state
            self._fault_pending = None
            return self._next_sequence()
        if self.state == "na":
            raise SimError("cannot abort: detector not initialized", status_code=409)
        await self._cancel_acquire_task()  # always ends the open series, if any (idempotent)
        self.state = "idle"
        return self._next_sequence()

    async def cancel(self) -> int:
        # Simplified: real SIMPLON finishes the image in flight before
        # stopping (unlike abort, which drops immediately); this simulator
        # does not model in-flight readout timing closely enough to
        # distinguish the two, so cancel behaves like abort. Documented in
        # RxDectris/python/README.md's "what is simulated" table.
        return await self.abort()

    # -- acquisition loop -----------------------------------------------------

    async def _run_series(self, series: _Series) -> None:
        try:
            for image_id in range(series.number_of_images):
                await asyncio.sleep(series.count_time)
                counts = 9000.0 + 400.0 * (image_id % 7)
                frame = {
                    "type": "image",
                    "series_id": series.series_id,
                    "series_unique_id": series.series_unique_id,
                    "image_id": image_id,
                    "real_time": series.count_time,
                    "start_time": time.time(),
                    "stop_time": time.time() + series.count_time,
                    "counts": counts,
                }
                self.progress = {"image_id": image_id, "number_of_images": series.number_of_images}
                await self._emit(frame)
                self._on_monitor_frame(frame)
            await self._end_series()
            self.state = "idle"  # auto-disarm, per SIMPLON ints/exts note
        except asyncio.CancelledError:
            return

    async def _end_series(self) -> None:
        if self._current is not None and not self._current.ended:
            self._current.ended = True
            await self._emit({
                "type": "end",
                "series_id": self._current.series_id,
                "series_unique_id": self._current.series_unique_id,
            })

    async def _cancel_acquire_task(self) -> None:
        if self._acquire_task is not None and not self._acquire_task.done():
            self._acquire_task.cancel()
            try:
                await self._acquire_task
            except asyncio.CancelledError:
                pass
        self._acquire_task = None
        await self._end_series()

    async def _raise_fault(self) -> None:
        fault = self._fault_pending
        self._fault_pending = None
        self.state = "error"
        raise SimError(f"detector fault injected: {fault}", status_code=500)

    # -- fault injection ----------------------------------------------------

    def set_fault(self, value: str) -> None:
        self._fault_pending = None if value == "nominal" else value
