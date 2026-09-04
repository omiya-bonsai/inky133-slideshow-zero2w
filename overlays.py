"""P-mode-safe date and status overlays."""

from __future__ import annotations

import logging
import random
from datetime import datetime
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

from profiles.model import OverlayDefaults


logger = logging.getLogger("inky_slideshow")
FontLoader = Callable[[int], ImageFont.ImageFont | ImageFont.FreeTypeFont]


def format_date_and_elapsed_time(
    capture_date: datetime | None,
    *,
    now: datetime | None = None,
) -> tuple[str, str, str]:
    if capture_date is None:
        return "Unknown date", "Unknown date", "Unknown date"

    current = now or datetime.now()
    formatted_date = capture_date.strftime("%Y-%m-%d")
    days = (current - capture_date).days

    if days >= 365:
        years = days // 365
        elapsed_text = f"{years} {'year' if years == 1 else 'years'} ago"
    elif days >= 30:
        months = days // 30
        elapsed_text = f"{months} {'month' if months == 1 else 'months'} ago"
    else:
        elapsed_text = "Within a month"

    if days >= 0:
        days_ago_text = f"{days} days ago (from today)"
    else:
        days_ago_text = f"{abs(days)} days from today"

    return formatted_date, elapsed_text, days_ago_text


def format_uptime(uptime_seconds: int) -> str:
    uptime_seconds = max(0, int(uptime_seconds))
    days, remainder = divmod(uptime_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days > 0:
        unit = "day" if days == 1 else "days"
        return f"{days} {unit}, {hours:02d}:{minutes:02d}:{seconds:02d}"
    return f"{hours:02d}:{minutes:02d}:{seconds:02d}"


def system_uptime_seconds() -> int:
    try:
        first = Path("/proc/uptime").read_text(encoding="utf-8").split()[0]
        return max(0, int(float(first)))
    except Exception:
        return 0


def make_font_loader(font_path: str) -> FontLoader:
    def load_font(size: int) -> ImageFont.ImageFont | ImageFont.FreeTypeFont:
        try:
            return ImageFont.truetype(font_path, size)
        except OSError:
            logger.warning("Font unavailable: %s", font_path)
            return ImageFont.load_default()

    return load_font


def _overlay_colours(
    image: Image.Image,
    settings: OverlayDefaults,
) -> tuple[int | tuple[int, int, int], int | tuple[int, int, int]]:
    if image.mode == "P" and image.palette is None:
        raise ValueError("P-mode image is missing its palette")
    if image.mode == "P":
        return settings.foreground_index, settings.background_index
    if image.mode == "RGB":
        return settings.foreground_rgb, settings.background_rgb
    raise ValueError(f"Expected P-mode or RGB image, got {image.mode}")


def add_date_overlay(
    image: Image.Image,
    capture_date: datetime | None,
    settings: OverlayDefaults,
    *,
    font_loader: FontLoader,
    rng: random.Random | random.Random = random,
    now: datetime | None = None,
) -> tuple[Image.Image, str]:
    """Draw the production-compatible date block without changing mode."""

    foreground, background = _overlay_colours(image, settings)
    draw = ImageDraw.Draw(image)
    font_small = font_loader(settings.font_size)
    font_large = font_loader(settings.date_font_size)
    date_text, elapsed_text, days_ago_text = format_date_and_elapsed_time(
        capture_date, now=now
    )
    position = rng.choice(settings.positions)
    margin = settings.margin
    padding = settings.background_padding

    bbox1 = draw.textbbox((0, 0), date_text, font=font_large)
    bbox2 = draw.textbbox((0, 0), elapsed_text, font=font_small)
    bbox3 = draw.textbbox((0, 0), days_ago_text, font=font_small)
    width = max(
        bbox1[2] - bbox1[0],
        bbox2[2] - bbox2[0],
        bbox3[2] - bbox3[0],
    )
    h1 = bbox1[3] - bbox1[1]
    h2 = bbox2[3] - bbox2[1]
    h3 = bbox3[3] - bbox3[1]
    height = h1 + h2 + h3 + settings.text_padding * 2

    if "right" in position:
        x = image.width - width - margin - padding
    else:
        x = margin + padding
    if "bottom" in position:
        y = image.height - height - margin - padding
    else:
        y = margin + padding

    draw.rectangle(
        (x - padding, y - padding, x + width + padding, y + height + padding),
        fill=background,
    )
    draw.text(
        (x, y),
        date_text,
        fill=foreground,
        font=font_large,
    )
    y2 = y + h1 + settings.text_padding
    draw.text(
        (x, y2),
        elapsed_text,
        fill=foreground,
        font=font_small,
    )
    y3 = y2 + h2 + settings.text_padding
    draw.text(
        (x, y3),
        days_ago_text,
        fill=foreground,
        font=font_small,
    )
    return image, position


def add_status_overlay(
    image: Image.Image,
    date_position: str,
    updated_at: datetime,
    settings: OverlayDefaults,
    *,
    font_loader: FontLoader,
    uptime_seconds: int | None = None,
) -> Image.Image:
    """Draw Updated/Uptime in the corner opposite the date block."""

    foreground, background = _overlay_colours(image, settings)
    draw = ImageDraw.Draw(image)
    font = font_loader(settings.font_size)
    updated = f"Updated: {updated_at.strftime('%Y-%m-%d %H:%M')}"
    uptime = format_uptime(
        system_uptime_seconds() if uptime_seconds is None else uptime_seconds
    )
    text_block = f"{updated}\nUptime: {uptime}"
    opposite = {
        "bottom-right": "top-left",
        "top-right": "bottom-left",
        "top-left": "bottom-right",
        "bottom-left": "top-right",
    }.get(date_position, "bottom-left")
    margin = settings.margin
    padding = settings.background_padding
    bbox = draw.multiline_textbbox(
        (0, 0), text_block, font=font, spacing=settings.line_spacing
    )
    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    if "right" in opposite:
        x = image.width - width - margin - padding
    else:
        x = margin + padding
    if "bottom" in opposite:
        y = image.height - height - margin - padding
    else:
        y = margin + padding

    draw.rectangle(
        (x - padding, y - padding, x + width + padding, y + height + padding),
        fill=background,
    )
    draw.multiline_text(
        (x, y),
        text_block,
        fill=foreground,
        font=font,
        spacing=settings.line_spacing,
    )
    return image


def render_overlays(
    image: Image.Image,
    capture_date: datetime | None,
    updated_at: datetime,
    settings: OverlayDefaults,
    *,
    font_path: str,
    rng: random.Random | random.Random = random,
    now: datetime | None = None,
    uptime_seconds: int | None = None,
) -> tuple[Image.Image, str]:
    font_loader = make_font_loader(font_path)
    image, position = add_date_overlay(
        image,
        capture_date,
        settings,
        font_loader=font_loader,
        rng=rng,
        now=now,
    )
    return (
        add_status_overlay(
            image,
            position,
            updated_at,
            settings,
            font_loader=font_loader,
            uptime_seconds=uptime_seconds,
        ),
        position,
    )
