#!/usr/bin/env python3
"""Run Phase3 using the installed production slideshow components."""

from __future__ import annotations

import logging
import socket
import sys
from dataclasses import replace
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[3]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from buttons import ButtonController  # noqa: E402
from config import load_config, setup_logging  # noqa: E402
from display import InkyDisplay  # noqa: E402
from metadata import MetadataIndex  # noqa: E402
from profiles import load_profile  # noqa: E402
from queue import SlideshowQueue  # noqa: E402
from slideshow import Slideshow  # noqa: E402


def experiment_profile():
    production = load_profile("inky133")
    return replace(
        production,
        key="inky133_phase3",
        display_name='Inky Impression 13.3" Adaptive Enhancement Phase3',
        input_mode="RGB",
        image_directory="photos/adaptive-enhancement/phase3",
        metadata_path="photos/adaptive-enhancement/metadata.json",
        state_suffix="133_phase3",
    )


def experiment_config(profile):
    """Load shared settings but never inherit production library overrides."""
    base = load_config(profile, project_root=PROJECT_ROOT)
    return replace(
        base,
        image_directory=(
            PROJECT_ROOT / "photos/adaptive-enhancement/phase3"
        ).resolve(strict=False),
        metadata_path=(
            PROJECT_ROOT / "photos/adaptive-enhancement/metadata.json"
        ).resolve(strict=False),
    )


def main() -> int:
    profile = experiment_profile()
    runtime = experiment_config(profile)
    logger = setup_logging(runtime)
    logger.info("=== %s starting ===", profile.display_name)
    logger.info("Profile: %s", profile.key)
    logger.info("Mode: %s", profile.input_mode)
    logger.info("Image directory: %s", runtime.image_directory)
    logger.info("Metadata file: %s", runtime.metadata_path)
    actual_hostname = socket.gethostname().split(".", 1)[0]
    if actual_hostname != profile.hostname:
        logger.warning(
            "Hostname differs from profile default: actual=%s / profile=%s",
            actual_hostname,
            profile.hostname,
        )

    metadata = MetadataIndex.load(runtime.metadata_path)
    display = InkyDisplay.initialize(profile)
    slideshow_queue = SlideshowQueue(runtime.state_file)
    slideshow = Slideshow(runtime, display, metadata, slideshow_queue)
    buttons = ButtonController(profile.buttons, slideshow.request_next)
    handles = buttons.start()
    logging.getLogger("inky_slideshow").debug(
        "Retained %d button handles", len(handles)
    )
    try:
        slideshow.run_forever()
    except KeyboardInterrupt:
        logger.info("Phase3 experiment stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
