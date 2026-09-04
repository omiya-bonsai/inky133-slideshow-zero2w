"""Persistent, shuffled slideshow queue."""

from __future__ import annotations

import json
import importlib.util
import logging
import os
import random
import sysconfig
import tempfile
from pathlib import Path
from typing import Protocol


logger = logging.getLogger("inky_slideshow")


# This filename is part of the requested public architecture, but it also
# shadows Python's standard-library ``queue`` module when the project root is
# on sys.path. Re-export the stdlib API so libraries such as gpiozero remain
# unaffected after this module has been imported.
_stdlib_queue_path = Path(sysconfig.get_path("stdlib")) / "queue.py"
_stdlib_queue_spec = importlib.util.spec_from_file_location(
    "_inky_slideshow_stdlib_queue", _stdlib_queue_path
)
if _stdlib_queue_spec is None or _stdlib_queue_spec.loader is None:
    raise ImportError(f"Cannot load standard-library queue: {_stdlib_queue_path}")
_stdlib_queue = importlib.util.module_from_spec(_stdlib_queue_spec)
_stdlib_queue_spec.loader.exec_module(_stdlib_queue)
Empty = _stdlib_queue.Empty
Full = _stdlib_queue.Full
Queue = _stdlib_queue.Queue
PriorityQueue = _stdlib_queue.PriorityQueue
LifoQueue = _stdlib_queue.LifoQueue
SimpleQueue = _stdlib_queue.SimpleQueue


class Shuffler(Protocol):
    def shuffle(self, values: list[str]) -> None: ...


def collect_images(image_directory: Path) -> list[str]:
    """Collect only direct ``photos/auto/*.png`` children."""

    if not image_directory.exists():
        return []
    return sorted(
        str(path.resolve())
        for path in image_directory.glob("*.png")
        if path.is_file() and not path.name.startswith(".")
    )


class SlideshowQueue:
    def __init__(
        self,
        state_file: Path,
        *,
        shuffler: Shuffler | None = None,
    ) -> None:
        self.state_file = state_file
        self.shuffler = shuffler or random
        self.total_count = 0
        self.items: list[str] = []

    def load(self) -> None:
        try:
            with self.state_file.open("r", encoding="utf-8") as handle:
                state = json.load(handle)
            self.total_count = int(state.get("total_count", 0))
            raw_queue = state.get("queue", [])
            self.items = [str(item) for item in raw_queue]
        except Exception:
            self.total_count = 0
            self.items = []

    def reconcile(self, current_images: list[str]) -> None:
        if self.total_count != len(current_images):
            logger.info(
                "Image count changed: %d -> %d; resetting queue",
                self.total_count,
                len(current_images),
            )
            self.items = []
            self.total_count = len(current_images)
            return

        current_set = set(current_images)
        self.items = [
            path
            for path in self.items
            if path in current_set and os.path.exists(path)
        ]
        self.total_count = len(current_images)

    def refill(self, current_images: list[str]) -> None:
        self.items = current_images.copy()
        self.shuffler.shuffle(self.items)
        self.total_count = len(current_images)
        logger.info("Image queue created: %d images", len(self.items))

    def pop(self) -> str:
        return self.items.pop(0)

    def save(self) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "total_count": self.total_count,
            "queue": self.items,
        }
        temporary_name: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.state_file.parent,
                prefix=f".{self.state_file.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_name = handle.name
                json.dump(payload, handle, ensure_ascii=False, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_name, self.state_file)
        except Exception:
            logger.exception("Failed to save state")
            if temporary_name:
                try:
                    Path(temporary_name).unlink(missing_ok=True)
                except OSError:
                    pass
