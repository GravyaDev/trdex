"""Risk management — external stop-loss engine, independent of AI agents."""

from trdex.risk.stop_loss import (
    KillSwitch,
    StopLossEvent,
    StopLossMonitor,
    StopReason,
    get_kill_switch,
)

__all__ = [
    "KillSwitch",
    "StopLossEvent",
    "StopLossMonitor",
    "StopReason",
    "get_kill_switch",
]
