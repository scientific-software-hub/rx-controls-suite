"""Value types for the SIMPLON detector lifecycle and Stream V2 messages.

Field names follow the *SIMPLON 1.8 API documentation, v3.5* (DECTRIS Ltd.,
2025-01-14) literally, so a value read from ``rxdectris`` and a value read
from the real DCU documentation line up 1:1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


#: The detector's documented status/state values. "na" means the DCU has just
#: booted or the acquisition service was restarted; "configure" and "test"
#: exist in the SIMPLON enum but are not driven by anything in this demo.
DETECTOR_STATES = ("na", "idle", "ready", "initialize", "configure", "acquire", "test", "error")


@dataclass(frozen=True)
class DetectorState:
    """A single ``GET /detector/api/1.8.0/status/state`` reading."""

    value: str

    @property
    def is_ready(self) -> bool:
        return self.value == "ready"

    @property
    def is_acquiring(self) -> bool:
        return self.value == "acquire"


@dataclass(frozen=True)
class AcquisitionConfig:
    """The subset of detector config parameters this demo drives."""

    count_time: float
    frame_time: float | None = None
    nimages: int = 1
    ntrigger: int = 1
    trigger_mode: str = "ints"


@dataclass(frozen=True)
class SeriesStart:
    """Stream V2 ``{"type": "start", ...}`` message — sent once per ``arm``."""

    series_id: int
    series_unique_id: str
    count_time: float
    frame_time: float
    number_of_images: int
    image_size_x: int
    image_size_y: int
    detector_description: str = "RxDectris simulated EIGER2"


@dataclass(frozen=True)
class Frame:
    """Stream V2 ``{"type": "image", ...}`` message — sent once per exposure."""

    series_id: int
    series_unique_id: str
    image_id: int
    real_time: float
    start_time: float
    stop_time: float
    counts: float
    data: bytes = b""
    user_data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SeriesEnd:
    """Stream V2 ``{"type": "end", ...}`` message — sent once per ``disarm``/``cancel``/``abort``."""

    series_id: int
    series_unique_id: str
