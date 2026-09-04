"""Profile data model for supported Inky displays."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


InputMode = Literal["P", "RGB"]


@dataclass(frozen=True)
class RefreshBehavior:
    """How the selected display is refreshed."""

    method: str = "show"
    full_refresh: bool = True


@dataclass(frozen=True)
class ButtonConfiguration:
    """GPIO and timing configuration for the two hardware buttons."""

    next_gpio: int = 5
    system_gpio: int = 6
    bounce_time: float = 0.08
    poweroff_hold_seconds: float = 3.0


@dataclass(frozen=True)
class OverlayDefaults:
    """Overlay geometry and palette indexes."""

    font_size: int
    date_font_size: int
    positions: tuple[str, ...]
    margin: int
    background_padding: int
    text_padding: int
    line_spacing: int
    foreground_index: int = 0
    background_index: int = 1
    foreground_rgb: tuple[int, int, int] = (0, 0, 0)
    background_rgb: tuple[int, int, int] = (255, 255, 255)


@dataclass(frozen=True)
class Profile:
    """All device-specific slideshow settings."""

    key: str
    display_name: str
    width: int
    height: int
    input_mode: InputMode
    display_driver: str
    refresh: RefreshBehavior
    buttons: ButtonConfiguration
    overlay: OverlayDefaults
    image_directory: str
    metadata_path: str
    default_interval: int
    hostname: str
    state_suffix: str

    def __post_init__(self) -> None:
        if not self.key.isidentifier():
            raise ValueError(f"Invalid profile key: {self.key!r}")
        if self.width <= 0 or self.height <= 0:
            raise ValueError("Display dimensions must be positive")
        if self.default_interval <= 0:
            raise ValueError("Default interval must be positive")
        if self.input_mode not in {"P", "RGB"}:
            raise ValueError(f"Unsupported input mode: {self.input_mode}")
        if ":" not in self.display_driver:
            raise ValueError(
                "display_driver must use 'module:factory' notation"
            )
