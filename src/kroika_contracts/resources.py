"""Read-only resources in a checkout or the standalone desktop bundle."""

from pathlib import Path
import sys


def resource_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS) / "kroika_resources"
    return Path(__file__).resolve().parents[2]
