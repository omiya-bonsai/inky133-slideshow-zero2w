#!/usr/bin/env python3
"""Slideshow orchestration.

Running this file directly remains supported so the existing 13.3-inch
systemd ``ExecStart=.../slideshow.py`` continues to use the default profile.
"""

from __future__ import annotations

import logging
import os
import random
import threading
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

from PIL import Image

from config import RuntimeConfig
from display import Display
from metadata import MetadataIndex
from overlays import render_overlays
from queue import SlideshowQueue, collect_images


logger = logging.getLogger("inky_slideshow")


def load_display_counter(path: Path) -> int:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except Exception:
        return 0


def save_display_counter(path: Path, counter: int) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(counter), encoding="utf-8")
    except Exception:
        logger.exception("Failed to save display counter")


def update_heartbeat(path: Path, *, now: datetime | None = None) -> None:
    try:
        path.write_text(
            (now or datetime.now()).isoformat(timespec="minutes"),
            encoding="utf-8",
        )
    except Exception:
        logger.exception("Failed to update heartbeat")


def prepare_image(
    image_path: str | Path,
    config: RuntimeConfig,
    metadata: MetadataIndex,
    updated_at: datetime,
    *,
    rng: random.Random | random.Random = random,
    now: datetime | None = None,
    uptime_seconds: int | None = None,
) -> Image.Image:
    """Open a finished profile PNG and add overlays without conversion."""

    with Image.open(image_path) as source:
        expected_mode = config.profile.input_mode
        if source.mode != expected_mode:
            raise ValueError(
                f"Generated image must be {expected_mode}-mode: {image_path} / "
                f"mode={source.mode}"
            )
        expected_size = (config.profile.width, config.profile.height)
        if source.size != expected_size:
            raise ValueError(
                f"Unexpected image size: {image_path} / {source.size}; "
                f"expected {expected_size}"
            )
        source.load()
        image = source.copy()

    if expected_mode == "P" and image.palette is None:
        raise ValueError(f"Missing palette: {image_path}")
    if expected_mode == "RGB" and image.getpalette() is not None:
        raise ValueError(f"RGB image must not have a palette: {image_path}")

    entry = metadata.lookup(image_path)
    if entry is None:
        logger.warning("Metadata entry not found: %s", Path(image_path).name)
        capture_date = None
    else:
        capture_date = entry.date

    image, _ = render_overlays(
        image,
        capture_date,
        updated_at,
        config.profile.overlay,
        font_path=config.font_path,
        rng=rng,
        now=now,
        uptime_seconds=uptime_seconds,
    )
    return image


class Slideshow:
    def __init__(
        self,
        config: RuntimeConfig,
        display: Display,
        metadata: MetadataIndex,
        queue: SlideshowQueue,
        *,
        next_image_event: threading.Event | None = None,
        rng: random.Random | random.Random = random,
        now: Callable[[], datetime] = datetime.now,
    ) -> None:
        self.config = config
        self.display = display
        self.metadata = metadata
        self.queue = queue
        self.next_image_event = next_image_event or threading.Event()
        self.rng = rng
        self.now = now
        self.counter = load_display_counter(config.counter_file)
        self.current_images: list[str] = []

    def request_next(self) -> None:
        self.next_image_event.set()

    def initialize(self) -> None:
        self.queue.load()
        self.current_images = collect_images(self.config.image_directory)
        if not self.current_images:
            raise RuntimeError(
                f"No PNG images found: {self.config.image_directory}"
            )
        self.queue.reconcile(self.current_images)

    def _ensure_queue(self) -> bool:
        if self.queue.items:
            return True
        self.current_images = collect_images(self.config.image_directory)
        if not self.current_images:
            logger.error("No PNG images found: %s", self.config.image_directory)
            return False
        self.queue.refill(self.current_images)
        return True

    def display_next(self) -> bool:
        """Display one image. Return False only if the library is empty."""

        while self._ensure_queue():
            image_path = self.queue.pop()
            if not os.path.exists(image_path):
                logger.warning("Missing image skipped: %s", image_path)
                self.queue.save()
                continue

            self.counter += 1
            updated_at = self.now()
            entry = self.metadata.lookup(image_path)
            display_mode = entry.display_mode if entry else "unknown"
            source = entry.source if entry else None
            logger.info(
                "Displaying #%d: %s / mode=%s / source=%s",
                self.counter,
                image_path,
                display_mode,
                source or "unknown",
            )

            try:
                image = prepare_image(
                    image_path,
                    self.config,
                    self.metadata,
                    updated_at,
                    rng=self.rng,
                )
                logger.info(
                    "Prepared: mode=%s / size=%s / palette_colours=%d",
                    image.mode,
                    image.size,
                    len(image.palette.colors) if image.palette else 0,
                )
                self.display.set_image(image)
                self.display.show()
                save_display_counter(self.config.counter_file, self.counter)
                self.queue.save()
                update_heartbeat(self.config.heartbeat_path)
                logger.info("Display completed: #%d", self.counter)
                return True
            except Exception:
                logger.exception("Failed to display image: %s", image_path)
                return True
        return False

    def run_forever(self) -> None:
        self.initialize()
        while True:
            displayed = self.display_next()
            if not displayed:
                time.sleep(60)
                continue
            self.next_image_event.clear()
            self.next_image_event.wait(self.config.interval_seconds)


if __name__ == "__main__":
    # Compatibility entry point for the production 13.3-inch service.
    from main import main

    raise SystemExit(main())
