"""Experiment-only mode and family-age overlays."""

from __future__ import annotations

import random
from datetime import datetime
from typing import TYPE_CHECKING

from PIL import Image, ImageDraw

from experiments.inky133_apple_framework_enhancement.family_age import family_age_labels

if TYPE_CHECKING:
    from profiles.model import OverlayDefaults

try:
    from .catalog import EffectEntry
except ImportError:
    from catalog import EffectEntry


_OPPOSITE_CORNER = {
    "top-left": "bottom-right",
    "top-right": "bottom-left",
    "bottom-left": "top-right",
    "bottom-right": "top-left",
}


class _FixedChoice:
    def __init__(self, value: str) -> None:
        self.value = value

    def choice(self, _values: tuple[str, ...]) -> str:
        return self.value


def choose_photo_overlay_positions(
    settings: OverlayDefaults,
    *,
    rng: random.Random | random.Random = random,
) -> tuple[str, str, str]:
    """Choose unique corners for date, status, and mode/age captions."""

    positions = tuple(
        dict.fromkeys(
            position
            for position in settings.positions
            if position in _OPPOSITE_CORNER
        )
    )
    if len(positions) < 3:
        raise ValueError("Photo overlays require at least three unique corner positions")
    date_position, status_position, age_position = rng.sample(positions, 3)
    return date_position, status_position, age_position


def effect_overlay_lines(entry: EffectEntry) -> tuple[str, ...]:
    """Return the experiment-only mode/age lines for one metadata entry."""

    if entry.category == "illustration":
        return ()
    lines = [entry.display_mode]
    if entry.vision_person_detected or entry.vision_face_count > 0:
        ages = family_age_labels(entry.capture_date)
        if ages:
            lines.append(" / ".join(ages))
    return tuple(lines)


def add_effect_overlay(
    image: Image.Image,
    entry: EffectEntry,
    settings: OverlayDefaults,
    *,
    font_path: str,
    position: str,
) -> Image.Image:
    from overlays import make_font_loader

    if image.mode != "RGB":
        raise ValueError(f"Effect overlay requires RGB, got {image.mode}")
    lines = effect_overlay_lines(entry)
    draw = ImageDraw.Draw(image)
    font = make_font_loader(font_path)(settings.font_size)
    text = "\n".join(lines)
    box = draw.multiline_textbbox((0, 0), text, font=font, spacing=4)
    width = box[2] - box[0]
    height = box[3] - box[1]
    padding = settings.background_padding
    if "right" in position:
        x = image.width - width - settings.margin - padding
    else:
        x = settings.margin + padding
    if "bottom" in position:
        y = image.height - height - settings.margin - padding
    else:
        y = settings.margin + padding
    draw.rectangle(
        (x - padding, y - padding, x + width + padding, y + height + padding),
        fill=settings.background_rgb,
    )
    draw.multiline_text(
        (x - box[0], y - box[1]),
        text,
        fill=settings.foreground_rgb,
        font=font,
        spacing=4,
        align="center",
    )
    return image


def prepare_effect_image(
    entry: EffectEntry,
    settings: OverlayDefaults,
    *,
    font_path: str,
    updated_at: datetime,
    now: datetime | None = None,
    uptime_seconds: int | None = None,
    rng: random.Random | random.Random = random,
) -> Image.Image:
    from overlays import add_status_overlay, make_font_loader

    with Image.open(entry.path) as opened:
        opened.load()
        if opened.format != "PNG" or opened.mode != "RGB" or opened.size != (1600, 1200):
            raise ValueError(
                f"Invalid effect PNG {entry.path}: format={opened.format}, mode={opened.mode}, size={opened.size}"
            )
        if opened.getpalette() is not None:
            raise ValueError(f"Effect RGB PNG has a palette: {entry.path}")
        image = opened.copy()
    if entry.category == "illustration":
        return add_status_overlay(
            image,
            "top-right",
            updated_at,
            settings,
            font_loader=make_font_loader(font_path),
            uptime_seconds=uptime_seconds,
        )
    from overlays import add_date_overlay

    date_position, status_position, age_position = choose_photo_overlay_positions(
        settings, rng=rng
    )
    font_loader = make_font_loader(font_path)
    image, _ = add_date_overlay(
        image,
        entry.capture_date,
        settings,
        font_loader=font_loader,
        rng=_FixedChoice(date_position),
        now=now,
    )
    image = add_status_overlay(
        image,
        _OPPOSITE_CORNER[status_position],
        updated_at,
        settings,
        font_loader=font_loader,
        uptime_seconds=uptime_seconds,
    )
    return add_effect_overlay(
        image,
        entry,
        settings,
        font_path=font_path,
        position=age_position,
    )
