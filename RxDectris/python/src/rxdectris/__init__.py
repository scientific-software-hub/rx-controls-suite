"""rxdectris — Reactive streams for DECTRIS detectors (SIMPLON API)."""

from rxdectris.client import DectrisClient
from rxdectris.command import abort, arm, cancel, disarm, initialize, send_command, trigger
from rxdectris.config import read_config, write_config
from rxdectris.context import DetectorContext
from rxdectris.models import (
    AcquisitionConfig,
    DetectorState,
    Frame,
    SeriesEnd,
    SeriesStart,
)
from rxdectris.monitor import monitor_images
from rxdectris.recipes import acquire_series
from rxdectris.status import monitor_state, read_status
from rxdectris.stream import configure_stream, stream2

__all__ = [
    "read_config",
    "write_config",
    "read_status",
    "monitor_state",
    "send_command",
    "initialize",
    "arm",
    "trigger",
    "disarm",
    "abort",
    "cancel",
    "stream2",
    "configure_stream",
    "monitor_images",
    "DetectorContext",
    "DectrisClient",
    "acquire_series",
    "DetectorState",
    "AcquisitionConfig",
    "Frame",
    "SeriesStart",
    "SeriesEnd",
]
