"""Pure evaluation, queue, overlay and JSONL logging components."""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Sequence

from PIL import Image, ImageDraw, ImageFont, UnidentifiedImageError

try:
    from .display import update_display
except ImportError:  # Direct execution on Raspberry Pi.
    from display import update_display


DISPLAY_SIZE = (1600, 1200)
SPECTRA6_PALETTE = (
    (0, 0, 0),
    (255, 255, 255),
    (255, 255, 0),
    (255, 0, 0),
    (0, 0, 255),
    (0, 255, 0),
)
STYLE_LABELS = frozenset({"Classic", "Illustrated", "Poster", "Vintage", "Watercolor"})
STYLE_OVERLAY_MARGIN = 18
STYLE_OVERLAY_PADDING = 12
STYLE_OVERLAY_LINE_GAP = 3
STYLE_OVERLAY_FONT_SIZE = 24
DEFAULT_DEBUG_OVERLAY_PATH = Path("/tmp/debug-overlay.png")


logger = logging.getLogger("inky133_style_evaluation")


class EvaluationError(RuntimeError):
    """A safe, user-facing evaluation error."""


@dataclass(frozen=True, slots=True)
class EvaluationEntry:
    source: str
    rendered: str
    style: str


def load_entries(metadata_path: Path) -> list[EvaluationEntry]:
    try:
        payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvaluationError(f"Cannot read style metadata: {metadata_path}: {exc}") from exc
    records = payload.get("entries") if isinstance(payload, dict) else None
    if not isinstance(records, dict):
        raise EvaluationError("Style metadata must contain an entries object")
    entries: list[EvaluationEntry] = []
    for key, record in records.items():
        if not isinstance(record, dict):
            raise EvaluationError(f"Invalid metadata entry: {key}")
        source = record.get("source")
        rendered = record.get("rendered")
        style = record.get("style")
        if not all(isinstance(value, str) and value for value in (source, rendered, style)):
            raise EvaluationError(f"Incomplete metadata entry: {key}")
        if style not in STYLE_LABELS:
            raise EvaluationError(f"Unknown style label in metadata: {style}")
        entries.append(EvaluationEntry(source, rendered, style))
    if not entries:
        raise EvaluationError("Style metadata contains no entries")
    return entries


def shuffled_entries(
    entries: Sequence[EvaluationEntry],
    rng: random.Random | random.Random = random,
) -> list[EvaluationEntry]:
    """Shuffle style/photo pairs while avoiding adjacent identical sources."""
    result = list(entries)
    rng.shuffle(result)
    for index in range(1, len(result)):
        if result[index].source != result[index - 1].source:
            continue
        replacement = next(
            (candidate for candidate in range(index + 1, len(result)) if result[candidate].source != result[index - 1].source),
            None,
        )
        if replacement is not None:
            result[index], result[replacement] = result[replacement], result[index]
    return result


def _resolve_rendered(entry: EvaluationEntry, library_root: Path) -> Path:
    root = library_root.resolve(strict=True)
    candidate = (root.parent / entry.rendered).resolve(strict=True)
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EvaluationError(f"Rendered image escapes style library: {entry.rendered}") from exc
    if not candidate.is_file():
        raise EvaluationError(f"Rendered image is not a file: {candidate}")
    return candidate


def load_style_image(entry: EvaluationEntry, library_root: Path) -> Image.Image:
    path = _resolve_rendered(entry, library_root)
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "P" or opened.size != DISPLAY_SIZE:
                raise EvaluationError(
                    f"Invalid style PNG {path}: format={opened.format}, mode={opened.mode}, size={opened.size}"
                )
            palette = opened.getpalette()
            if palette is None:
                raise EvaluationError(f"Style PNG has no palette: {path}")
            actual = tuple(tuple(palette[offset:offset + 3]) for offset in range(0, 18, 3))
            if actual != SPECTRA6_PALETTE:
                raise EvaluationError(f"Style PNG has the wrong Spectra 6 palette: {path}")
            colours = opened.getcolors(maxcolors=256) or []
            invalid = sorted(index for _count, index in colours if index > 5)
            if invalid:
                raise EvaluationError(f"Style PNG has invalid palette indexes: {invalid}")
            return opened.copy()
    except UnidentifiedImageError as exc:
        raise EvaluationError(f"Unreadable style PNG: {path}") from exc


def _font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
    for path in (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/freefont/FreeSans.ttf",
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            pass
    return ImageFont.load_default()


def style_overlay_lines(style: str) -> tuple[str, ...]:
    """Return the compact, fixed operator guide shown during evaluation."""
    return (
        f"STYLE: {style}",
        "Hold A ♥ LIKE",
        "Press B × DISLIKE",
        "Hold B → Power Off",
    )


def add_label_overlay(image: Image.Image, text: str, *, feedback: bool = False) -> Image.Image:
    if image.mode != "P" or image.size != DISPLAY_SIZE:
        raise EvaluationError("Style overlays require a 1600x1200 P-mode image")
    result = image.copy()
    draw = ImageDraw.Draw(result)
    font = _font(36 if feedback else STYLE_OVERLAY_FONT_SIZE)
    lines = (text,) if feedback else style_overlay_lines(text)
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    padding = 14 if feedback else STYLE_OVERLAY_PADDING
    line_gap = 0 if feedback else STYLE_OVERLAY_LINE_GAP
    width = max(box[2] - box[0] for box in boxes) + padding * 2
    text_heights = [box[3] - box[1] for box in boxes]
    height = sum(text_heights) + line_gap * (len(lines) - 1) + padding * 2
    if feedback:
        x = (result.width - width) // 2
        y = (result.height - height) // 2
    else:
        x = result.width - width - STYLE_OVERLAY_MARGIN
        y = result.height - height - STYLE_OVERLAY_MARGIN
    # P-mode indexes 1/0 are the fixed Spectra 6 white/black colours.
    draw.rectangle((x, y, x + width, y + height), fill=1, outline=0, width=1)
    text_y = y + padding
    for line, box, text_height in zip(lines, boxes, text_heights, strict=True):
        draw.text((x + padding, text_y - box[1]), line, font=font, fill=0)
        text_y += text_height + line_gap
    return result


class JsonlEvaluationLog:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, object]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(record, ensure_ascii=False, separators=(",", ":")) + "\n"
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())


class StyleEvaluator:
    """Show randomized entries and record exactly one rating per display."""

    def __init__(
        self,
        display: object,
        entries: Sequence[EvaluationEntry],
        library_root: Path,
        evaluation_log: JsonlEvaluationLog,
        *,
        rng: random.Random | random.Random = random,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] = lambda: datetime.now().astimezone(),
        feedback_seconds: float = 0.8,
        debug_overlay_path: Path = DEFAULT_DEBUG_OVERLAY_PATH,
    ) -> None:
        self.display = display
        self.entries = list(entries)
        self.library_root = library_root
        self.log = evaluation_log
        self.rng = rng
        self.sleeper = sleeper
        self.clock = clock
        self.now = now
        self.feedback_seconds = feedback_seconds
        self.debug_overlay_path = debug_overlay_path
        self.queue: list[EvaluationEntry] = []
        self.current: EvaluationEntry | None = None
        self.current_image: Image.Image | None = None
        self.shown_at: datetime | None = None
        self.shown_monotonic: float | None = None
        self._lock = threading.Lock()

    def _refill(self) -> None:
        self.queue = shuffled_entries(self.entries, self.rng)
        if self.current and len(self.queue) > 1 and self.queue[-1].source == self.current.source:
            self.queue[0], self.queue[-1] = self.queue[-1], self.queue[0]

    def show_next(self) -> EvaluationEntry:
        if not self.queue:
            self._refill()
        entry = self.queue.pop()
        logger.info("Selected source: %s", entry.source)
        logger.info("Selected style: %s", entry.style)
        image = load_style_image(entry, self.library_root)
        prepared = add_label_overlay(image, entry.style)
        prepared.save(self.debug_overlay_path, format="PNG")
        logger.info("Overlay created: %s", self.debug_overlay_path)
        logger.info("Display start")
        update_display(self.display, prepared)
        logger.info("Display completed")
        self.current = entry
        self.current_image = image
        self.shown_at = self.now()
        self.shown_monotonic = self.clock()
        logger.info("Waiting for evaluation")
        return entry

    def rate(self, rating: str) -> EvaluationEntry:
        if rating not in {"like", "dislike"}:
            raise EvaluationError(f"Unsupported rating: {rating}")
        with self._lock:
            if self.current is None or self.current_image is None or self.shown_at is None or self.shown_monotonic is None:
                raise EvaluationError("No displayed image is available to rate")
            entry = self.current
            evaluated_at = self.now()
            self.log.append(
                {
                    "timestamp": evaluated_at.isoformat(timespec="seconds"),
                    "shown_at": self.shown_at.isoformat(timespec="seconds"),
                    "display_seconds": round(max(0.0, self.clock() - self.shown_monotonic), 3),
                    "source": entry.source,
                    "rendered": entry.rendered,
                    "style": entry.style,
                    "rating": rating,
                }
            )
            logger.info(
                "Rating saved: source=%s style=%s rating=%s",
                entry.source,
                entry.style,
                rating,
            )
            feedback = "LIKE ♥" if rating == "like" else "DISLIKE"
            prepared = add_label_overlay(add_label_overlay(self.current_image, entry.style), feedback, feedback=True)
            update_display(self.display, prepared)
            self.sleeper(self.feedback_seconds)
            logger.info("Next image")
            return self.show_next()
