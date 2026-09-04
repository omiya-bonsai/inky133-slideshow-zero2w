#!/usr/bin/env python3
"""Command-line entry point for the multi-profile slideshow."""

from __future__ import annotations

import argparse
import logging
import socket

from buttons import ButtonController
from config import load_config, setup_logging
from display import DummyDisplay, InkyDisplay
from metadata import MetadataIndex
from profiles import load_profile, profile_names
from queue import SlideshowQueue
from slideshow import Slideshow


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inky multi-profile slideshow")
    parser.add_argument(
        "--profile",
        choices=profile_names(),
        default="inky133",
        help="display profile (default: inky133)",
    )
    parser.add_argument(
        "--dummy",
        action="store_true",
        help="use an in-memory display instead of Inky hardware",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    profile = load_profile(args.profile)
    config = load_config(profile)
    logger = setup_logging(config)
    logger.info("=== %s slideshow starting ===", profile.display_name)
    logger.info("Profile: %s", profile.key)
    logger.info("Mode: %s", profile.input_mode)
    logger.info("Image directory: %s", config.image_directory)
    logger.info("Metadata file: %s", config.metadata_path)

    actual_hostname = socket.gethostname().split(".", 1)[0]
    if actual_hostname != profile.hostname:
        logger.warning(
            "Hostname differs from profile default: actual=%s / profile=%s",
            actual_hostname,
            profile.hostname,
        )

    metadata = MetadataIndex.load(config.metadata_path)
    display = (
        DummyDisplay.for_profile(profile)
        if args.dummy
        else InkyDisplay.initialize(profile)
    )
    slideshow_queue = SlideshowQueue(config.state_file)
    slideshow = Slideshow(config, display, metadata, slideshow_queue)
    button_controller = ButtonController(
        profile.buttons,
        slideshow.request_next,
    )
    # Retain the gpiozero handles for the full process lifetime.
    button_handles = button_controller.start()
    logging.getLogger("inky_slideshow").debug(
        "Retained %d button handles", len(button_handles)
    )

    try:
        slideshow.run_forever()
    except KeyboardInterrupt:
        logger.info("Slideshow stopped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
