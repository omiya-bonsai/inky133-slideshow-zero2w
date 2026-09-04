"""Hardware and dummy display adapters."""

from __future__ import annotations

import importlib
import logging
from typing import Protocol

from PIL import Image

from profiles.model import Profile


logger = logging.getLogger("inky_slideshow")


class Display(Protocol):
    width: int
    height: int

    def set_image(self, image: Image.Image) -> None: ...

    def show(self) -> None: ...


def validate_display_image(
    image: Image.Image,
    width: int,
    height: int,
    input_mode: str = "P",
) -> None:
    if image.mode != input_mode:
        raise ValueError(
            f"Generated image must be {input_mode}-mode, got {image.mode}"
        )
    if image.size != (width, height):
        raise ValueError(
            f"Unexpected image size: {image.size}; expected {(width, height)}"
        )
    if input_mode == "P" and image.palette is None:
        raise ValueError("P-mode image is missing its palette")
    if input_mode == "RGB" and image.getpalette() is not None:
        raise ValueError("RGB image must not contain a palette")


class InkyDisplay:
    """Thin adapter around the Pimoroni driver; no image conversion occurs."""

    def __init__(self, device: object, profile: Profile) -> None:
        self._device = device
        self.profile = profile
        self.width = int(getattr(device, "width"))
        self.height = int(getattr(device, "height"))
        if (self.width, self.height) != (profile.width, profile.height):
            raise RuntimeError(
                "Unexpected display resolution: "
                f"{self.width}x{self.height}; expected "
                f"{profile.width}x{profile.height}"
            )

    @classmethod
    def initialize(cls, profile: Profile) -> "InkyDisplay":
        module_name, factory_name = profile.display_driver.split(":", 1)
        factory = getattr(importlib.import_module(module_name), factory_name)
        device = factory(verbose=True)
        logger.info(
            "Detected display: %s / %dx%d",
            type(device).__name__,
            device.width,
            device.height,
        )
        if hasattr(device, "set_border") and hasattr(device, "WHITE"):
            device.set_border(device.WHITE)
        return cls(device, profile)

    def set_image(self, image: Image.Image) -> None:
        validate_display_image(
            image,
            self.width,
            self.height,
            self.profile.input_mode,
        )
        self._device.set_image(image)

    def show(self) -> None:
        refresh_method = getattr(self._device, self.profile.refresh.method)
        refresh_method()


class DummyDisplay:
    """In-memory display used by tests and non-Pi validation."""

    def __init__(self, width: int, height: int, input_mode: str = "P") -> None:
        self.width = width
        self.height = height
        self.input_mode = input_mode
        self.last_image: Image.Image | None = None
        self.set_image_calls = 0
        self.show_calls = 0

    @classmethod
    def for_profile(cls, profile: Profile) -> "DummyDisplay":
        return cls(profile.width, profile.height, profile.input_mode)

    def set_image(self, image: Image.Image) -> None:
        validate_display_image(image, self.width, self.height, self.input_mode)
        self.last_image = image.copy()
        self.set_image_calls += 1

    def show(self) -> None:
        if self.last_image is None:
            raise RuntimeError("set_image must be called before show")
        self.show_calls += 1
