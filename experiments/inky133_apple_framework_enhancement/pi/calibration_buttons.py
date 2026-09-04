"""Experiment-local C/D controls while preserving production A/B behavior."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import Any

try:
    from buttons import ButtonController
except ImportError:  # Allows Mac-side unit tests without the Pi runtime checkout.
    ButtonController = None  # type: ignore[assignment,misc]


logger = logging.getLogger("inky133_apple_effects")


def el133uf1_chip_select_gpios() -> frozenset[int]:
    """Read the installed EL133UF1 chip-select mapping when available."""

    try:
        from inky.inky_el133uf1 import CS0_PIN, CS1_PIN
    except ImportError:  # Mac-side tests do not install the Pi-only Inky package.
        return frozenset((26, 16))
    return frozenset((int(CS0_PIN), int(CS1_PIN)))


class CalibrationButtonController:
    # Pimoroni's installed spectra6/buttons.py example explicitly remaps C from
    # GPIO16 to GPIO25 for Impression 13.3. GPIO16 is EL133UF1 chip-select 1.
    C_GPIO = 25
    D_GPIO = 24

    def __init__(
        self,
        configuration,
        request_next: Callable[[], None],
        calibration_c_short: Callable[[], None],
        calibration_c_long: Callable[[], None],
        calibration_d_short: Callable[[], None],
        calibration_d_long: Callable[[], None] | None = None,
        *,
        clock: Callable[[], float] = time.monotonic,
        long_press_seconds: float = 2.0,
        base_controller: Any | None = None,
    ) -> None:
        self.configuration = configuration
        self.clock = clock
        self.long_press_seconds = long_press_seconds
        self.calibration_c_short = calibration_c_short
        self.calibration_c_long = calibration_c_long
        self.calibration_d_short = calibration_d_short
        self.calibration_d_long = calibration_d_long
        if base_controller is None:
            if ButtonController is None:
                raise RuntimeError("Pi ButtonController is unavailable")
            base_controller = ButtonController(configuration, request_next)
        self.base = base_controller
        self._c_pressed_at: float | None = None
        self._d_pressed_at: float | None = None
        self._handles: list[Any] = []

    def start(self) -> list[Any]:
        chip_select_gpios = el133uf1_chip_select_gpios()
        conflicts = chip_select_gpios.intersection((self.C_GPIO, self.D_GPIO))
        if conflicts:
            pins = ", ".join(f"GPIO{pin}" for pin in sorted(conflicts))
            raise RuntimeError(
                f"Calibration button GPIO conflicts with EL133UF1 chip select: {pins}"
            )
        logger.info(
            "EL133UF1 GPIO mapping: chip-select=%s; calibration C=GPIO%d, D=GPIO%d",
            ",".join(f"GPIO{pin}" for pin in sorted(chip_select_gpios)),
            self.C_GPIO,
            self.D_GPIO,
        )
        handles = list(self.base.start())
        try:
            from gpiozero import Button
        except Exception as exc:
            logger.warning("gpiozero not available, calibration buttons disabled: %s", exc)
            self._handles = handles
            return handles
        c_button = Button(
            self.C_GPIO,
            pull_up=True,
            bounce_time=self.configuration.bounce_time,
        )
        d_button = Button(
            self.D_GPIO,
            pull_up=True,
            bounce_time=self.configuration.bounce_time,
        )
        c_button.when_pressed = self.on_c_pressed
        c_button.when_released = self.on_c_released
        d_button.when_pressed = self.on_d_pressed
        d_button.when_released = self.on_d_released
        handles.extend((c_button, d_button))
        self._handles = handles
        logger.info(
            "Color Calibration buttons enabled: "
            "C=GPIO%d (short=enter/next-target, long=exit), "
            "D=GPIO%d (short=strength/SAT-group, long=SAT-mode)",
            self.C_GPIO,
            self.D_GPIO,
        )
        return handles

    def on_c_pressed(self) -> None:
        self._c_pressed_at = self.clock()
        logger.info("Button C pressed")

    def on_c_released(self) -> None:
        if self._c_pressed_at is None:
            return
        held = self.clock() - self._c_pressed_at
        self._c_pressed_at = None
        if held >= self.long_press_seconds:
            self.calibration_c_long()
        else:
            self.calibration_c_short()

    def on_d_pressed(self) -> None:
        self._d_pressed_at = self.clock()
        logger.info("Button D pressed")

    def on_d_released(self) -> None:
        if self._d_pressed_at is None:
            return
        held = self.clock() - self._d_pressed_at
        self._d_pressed_at = None
        if held >= self.long_press_seconds:
            if self.calibration_d_long is None:
                logger.info("Button D long press has no action")
                return
            self.calibration_d_long()
            return
        self.calibration_d_short()
