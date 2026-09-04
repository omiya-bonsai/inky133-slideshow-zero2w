#!/usr/bin/env python3
"""Run the independent Inky133 Style Evaluation Mode on Raspberry Pi."""

from __future__ import annotations

import argparse
import logging
import queue
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable, Sequence

try:
    from .display import DisplayError, initialize_display
    from .evaluator import (
        EvaluationError,
        JsonlEvaluationLog,
        StyleEvaluator,
        load_entries,
        load_style_image,
    )
except ImportError:  # Direct execution on Raspberry Pi.
    from display import DisplayError, initialize_display
    from evaluator import (
        EvaluationError,
        JsonlEvaluationLog,
        StyleEvaluator,
        load_entries,
        load_style_image,
    )


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_LIBRARY = PROJECT_ROOT / "photos/styles"
DEFAULT_METADATA = PROJECT_ROOT / "photos/style-evaluation-metadata.json"
DEFAULT_LOG = PROJECT_ROOT / "experiments/logs/style-evaluation.jsonl"
SERVICE_NAME = "inky-slideshow.service"


logger = logging.getLogger("inky133_style_evaluation")


def configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def service_active() -> bool:
    if shutil.which("systemctl") is None:
        return False
    return subprocess.run(
        ["systemctl", "is-active", "--quiet", SERVICE_NAME],
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    ).returncode == 0


class EvaluationButtons:
    """A=LIKE, short-B=DISLIKE, long-B retains production poweroff."""

    def __init__(
        self,
        emit: Callable[[str], None],
        *,
        clock: Callable[[], float] = time.monotonic,
        command_runner: Callable[[list[str]], object] = subprocess.Popen,
        hold_seconds: float = 3.0,
    ) -> None:
        self.emit = emit
        self.clock = clock
        self.command_runner = command_runner
        self.hold_seconds = hold_seconds
        self.pressed_at: float | None = None
        self.handles: list[object] = []

    def on_like(self) -> None:
        logger.info("Button pressed: A / like")
        self.emit("like")

    def on_system_pressed(self) -> None:
        logger.info("Button pressed: B")
        self.pressed_at = self.clock()

    def on_system_released(self) -> None:
        if self.pressed_at is None:
            return
        held = self.clock() - self.pressed_at
        self.pressed_at = None
        if held >= self.hold_seconds:
            logger.info("Button action: B long hold / poweroff")
            self.command_runner(["sudo", "/usr/sbin/poweroff"])
        else:
            logger.info("Button action: B short press / dislike")
            self.emit("dislike")

    def start(self) -> list[object]:
        try:
            from gpiozero import Button
        except Exception as exc:
            raise EvaluationError(f"gpiozero is required for evaluation buttons: {exc}") from exc
        like = Button(5, pull_up=True, bounce_time=0.08)
        dislike = Button(6, pull_up=True, bounce_time=0.08)
        like.when_pressed = self.on_like
        dislike.when_pressed = self.on_system_pressed
        dislike.when_released = self.on_system_released
        self.handles = [like, dislike]
        return self.handles


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Inky133 Style Evaluation Mode")
    parser.add_argument("--library", type=Path, default=DEFAULT_LIBRARY)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--log", type=Path, default=DEFAULT_LOG)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def run(argv: Sequence[str] | None = None) -> int:
    configure_logging()
    args = build_parser().parse_args(argv)
    try:
        entries = load_entries(args.metadata)
        print("=== Inky133 Style Evaluation Mode ===")
        print(f"Candidates : {len(entries)}")
        print(f"Styles     : {len({entry.style for entry in entries})}")
        print(f"Log        : {args.log}")
        if args.dry_run:
            for entry in entries[: min(5, len(entries))]:
                load_style_image(entry, args.library)
            print(f"Validated  : {min(5, len(entries))} sample PNG(s)")
            print("Display    : skipped (--dry-run)")
            return 0
        if service_active():
            raise EvaluationError(
                f"{SERVICE_NAME} is active; stop it before accessing the display/buttons"
            )
        display = initialize_display()
        evaluator = StyleEvaluator(display, entries, args.library, JsonlEvaluationLog(args.log))
        events: queue.SimpleQueue[str] = queue.SimpleQueue()
        buttons = EvaluationButtons(events.put)
        button_handles = buttons.start()
        evaluator.show_next()
        print("Buttons    : A=LIKE / B short=DISLIKE / B long=poweroff")
        while button_handles:
            evaluator.rate(events.get())
        return 0
    except KeyboardInterrupt:
        print("Stopped")
        return 0
    except (DisplayError, EvaluationError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(run())
