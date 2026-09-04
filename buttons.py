"""GPIO button integration."""

from __future__ import annotations

import logging
import subprocess
import time
from collections.abc import Callable
from typing import Any

from profiles.model import ButtonConfiguration


logger = logging.getLogger("inky_slideshow")


class ButtonController:
    def __init__(
        self,
        configuration: ButtonConfiguration,
        request_next: Callable[[], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        command_runner: Callable[[list[str]], Any] = subprocess.Popen,
    ) -> None:
        self.configuration = configuration
        self.request_next = request_next
        self.clock = clock
        self.command_runner = command_runner
        self._system_pressed_at: float | None = None
        self._handles: list[Any] = []

    def start(self) -> list[Any]:
        try:
            from gpiozero import Button
        except Exception as exc:
            logger.warning("gpiozero not available, buttons disabled: %s", exc)
            return []

        next_button = Button(
            self.configuration.next_gpio,
            pull_up=True,
            bounce_time=self.configuration.bounce_time,
        )
        system_button = Button(
            self.configuration.system_gpio,
            pull_up=True,
            bounce_time=self.configuration.bounce_time,
        )
        next_button.when_pressed = self.on_next_pressed
        system_button.when_pressed = self.on_system_pressed
        system_button.when_released = self.on_system_released
        self._handles = [next_button, system_button]
        logger.info("Buttons enabled: A=next, B=reboot, long-B=poweroff")
        return self._handles

    def on_next_pressed(self) -> None:
        logger.info("Button A pressed: next image requested")
        self.request_next()

    def on_system_pressed(self) -> None:
        self._system_pressed_at = self.clock()
        logger.info("Button B pressed")

    def on_system_released(self) -> None:
        if self._system_pressed_at is None:
            return
        held = self.clock() - self._system_pressed_at
        self._system_pressed_at = None
        if held >= self.configuration.poweroff_hold_seconds:
            logger.warning("Button B long press %.2fs: poweroff", held)
            self.command_runner(["sudo", "/usr/sbin/poweroff"])
        else:
            logger.warning("Button B short press %.2fs: reboot", held)
            self.command_runner(["sudo", "/usr/sbin/reboot"])
