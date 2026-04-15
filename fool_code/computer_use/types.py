"""Type definitions for Computer Use tools."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DisplayInfo:
    display_id: int
    width: int
    height: int
    scale_factor: float
    origin_x: int
    origin_y: int


@dataclass
class ScreenshotResult:
    base64: str
    width: int
    height: int


@dataclass
class AppInfo:
    pid: int = 0
    exe: str = ""
    title: str = ""
    name: str = ""


@dataclass
class InstalledApp:
    name: str = ""
    path: str = ""
    exe: str = ""
