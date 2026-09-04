#!/usr/bin/env python3
"""Display pre-rendered Apple effect PNGs without Pi image processing."""

from __future__ import annotations

import logging
import os
import socket
import sys
import threading
import time
from dataclasses import replace
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from config import load_config, setup_logging  # noqa: E402
from display import InkyDisplay  # noqa: E402
from profiles import load_profile  # noqa: E402
from queue import SlideshowQueue  # noqa: E402
from slideshow import save_display_counter, update_heartbeat  # noqa: E402

try:
    from .calibration_buttons import CalibrationButtonController
    from .calibration_runtime import CalibrationSession
    from .catalog import CatalogError, EffectCatalog
    from .color_calibration import (
        CalibrationError,
        ColorCalibrationCatalog,
    )
    from .overlay import prepare_effect_image
except ImportError:
    from calibration_buttons import CalibrationButtonController
    from calibration_runtime import CalibrationSession
    from catalog import CatalogError, EffectCatalog
    from color_calibration import (
        CalibrationError,
        ColorCalibrationCatalog,
    )
    from overlay import prepare_effect_image


logger = logging.getLogger("inky133_apple_effects")


def experiment_profile():
    return replace(
        load_profile("inky133"),
        key="inky133_apple_effects",
        display_name='Inky Impression 13.3" Apple Framework Effects',
        input_mode="RGB",
        image_directory="photos/apple-effects",
        metadata_path="photos/apple-effects/metadata.json",
        state_suffix="133_apple_effects",
    )


class EffectSlideshow:
    def __init__(
        self,
        runtime,
        display,
        catalog: EffectCatalog,
        calibration_catalog: ColorCalibrationCatalog | None = None,
    ) -> None:
        self.runtime = runtime
        self.display = display
        self.catalog = catalog
        self.queue = SlideshowQueue(runtime.state_file)
        self.next_event = threading.Event()
        self.counter = 0
        try:
            self.counter = int(runtime.counter_file.read_text().strip())
        except Exception:
            pass
        self.tickets = catalog.weighted_tickets()
        self.calibration_session = CalibrationSession(
            display,
            calibration_catalog or ColorCalibrationCatalog.empty(),
            font_path=runtime.font_path,
        )

    def request_next(self) -> None:
        self.calibration_session.clear_for_next()
        self.next_event.set()

    def initialize(self) -> None:
        self.queue.load()
        self.queue.reconcile(self.tickets)

    def display_next(self) -> bool:
        if not self.queue.items:
            self.queue.refill(self.tickets)
        while self.queue.items:
            path = self.queue.pop()
            if not os.path.isfile(path):
                logger.warning("Missing effect image skipped: %s", path)
                self.queue.save()
                continue
            entry = self.catalog.lookup(path)
            self.counter += 1
            updated_at = datetime.now()
            logger.info(
                "Displaying #%d: %s / mode=%s / source=%s / fallback=%s",
                self.counter,
                path,
                entry.display_mode,
                entry.source,
                entry.fallback,
            )
            try:
                prepared = prepare_effect_image(
                    entry,
                    self.runtime.profile.overlay,
                    font_path=self.runtime.font_path,
                    updated_at=updated_at,
                )
                logger.info(
                    "Prepared: mode=%s / size=%s / palette_colours=0",
                    prepared.mode,
                    prepared.size,
                )
                logger.info("Display start")
                self.calibration_session.show_normal(entry, prepared)
                save_display_counter(self.runtime.counter_file, self.counter)
                self.queue.save()
                update_heartbeat(self.runtime.heartbeat_path)
                logger.info("Display completed: #%d", self.counter)
                return True
            except Exception:
                logger.exception("Failed to display effect image: %s", path)
                return True
        return False

    def calibration_c_short(self) -> None:
        self.calibration_session.c_short()

    def calibration_c_long(self) -> None:
        self.calibration_session.c_long()

    def calibration_d_short(self) -> None:
        self.calibration_session.d_short()

    def calibration_d_long(self) -> None:
        self.calibration_session.d_long()

    def run_forever(self) -> None:
        self.initialize()
        while True:
            if not self.display_next():
                time.sleep(60)
                continue
            self.next_event.clear()
            while True:
                requested = self.next_event.wait(self.runtime.interval_seconds)
                if requested or not self.calibration_session.is_active():
                    break


def main() -> int:
    profile = experiment_profile()
    base = load_config(profile, project_root=PROJECT_ROOT)
    library = (PROJECT_ROOT / "photos/apple-effects").resolve(strict=False)
    metadata = library / "metadata.json"
    runtime = replace(base, image_directory=library, metadata_path=metadata)
    log = setup_logging(runtime)
    log.info("=== %s starting ===", profile.display_name)
    log.info("Profile: %s", profile.key)
    log.info("Mode: RGB")
    log.info("Image directory: %s", library)
    log.info("Metadata file: %s", metadata)
    actual_hostname = socket.gethostname().split(".", 1)[0]
    if actual_hostname != profile.hostname:
        log.warning("Hostname differs: actual=%s / profile=%s", actual_hostname, profile.hostname)
    try:
        catalog = EffectCatalog.load(metadata, library)
    except CatalogError as exc:
        log.error("Cannot start effect catalog: %s", exc)
        return 2
    calibration_root = library / "calibration"
    calibration_manifest = calibration_root / "manifest.json"
    if calibration_manifest.is_file():
        try:
            calibration_catalog = ColorCalibrationCatalog.load(
                calibration_manifest,
                calibration_root,
            )
            log.info(
                "Color calibration assets: %d sources",
                len(calibration_catalog.entries),
            )
        except CalibrationError as exc:
            log.error("Color calibration disabled: %s", exc)
            calibration_catalog = ColorCalibrationCatalog.empty()
    else:
        log.info("Color calibration assets: none")
        calibration_catalog = ColorCalibrationCatalog.empty()
    display = InkyDisplay.initialize(profile)
    slideshow = EffectSlideshow(runtime, display, catalog, calibration_catalog)
    buttons = CalibrationButtonController(
        profile.buttons,
        slideshow.request_next,
        slideshow.calibration_c_short,
        slideshow.calibration_c_long,
        slideshow.calibration_d_short,
        slideshow.calibration_d_long,
    )
    handles = buttons.start()
    log.debug("Retained %d button handles", len(handles))
    try:
        slideshow.run_forever()
    except KeyboardInterrupt:
        log.info("Apple effect experiment stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
