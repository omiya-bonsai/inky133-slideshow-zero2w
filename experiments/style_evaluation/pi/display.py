"""Production-equivalent Inky133 display initialization and refresh."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Protocol

from PIL import Image


DISPLAY_SIZE = (1600, 1200)
logger = logging.getLogger("inky133_style_evaluation")


class DisplayError(RuntimeError):
    """Raised when the detected display or prepared image is invalid."""


class Display(Protocol):
    width: int
    height: int

    def set_image(self, image: Image.Image) -> None: ...

    def show(self) -> None: ...


def initialize_display(
    *,
    factory: Callable[..., object] | None = None,
) -> object:
    """Initialize Inky133 exactly like the working production slideshow."""

    if factory is None:
        try:
            from inky.auto import auto
        except ImportError as exc:
            raise DisplayError("Activate the Pimoroni virtualenv first") from exc
        factory = auto

    device = factory(verbose=True)
    width = getattr(device, "width", None)
    height = getattr(device, "height", None)
    logger.info(
        "Detected display: %s / %sx%s",
        type(device).__name__,
        width,
        height,
    )
    if (width, height) != DISPLAY_SIZE:
        raise DisplayError(
            f"Unexpected display resolution: {width}x{height}; expected 1600x1200"
        )
    if hasattr(device, "set_border") and hasattr(device, "WHITE"):
        device.set_border(device.WHITE)
    return device


def validate_display_image(image: Image.Image) -> None:
    """Validate a finished Inky133 image without converting it."""

    if image.mode != "P":
        raise DisplayError(f"Expected P-mode image, got {image.mode}")
    if image.size != DISPLAY_SIZE:
        raise DisplayError(
            f"Unexpected image size: {image.size}; expected {DISPLAY_SIZE}"
        )
    if image.palette is None:
        raise DisplayError("P-mode image is missing its palette")


def update_display(display: Display, image: Image.Image) -> None:
    """Send one prepared image through the production display path."""

    validate_display_image(image)
    display.set_image(image)
    display.show()
