"""Pi-safe composition of pre-rendered Color Calibration assets."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from PIL import Image, ImageDraw, ImageFont


WIDTH = 1600
HEIGHT = 1200
STRIPE_WIDTH = 400
MODES = ("RAW", "VIB", "SAT", "TONE")
STRENGTHS = ("S", "M", "H")
PATTERNS = (
    ("RAW", "VIB", "SAT", "TONE"),
    ("VIB", "SAT", "TONE", "RAW"),
    ("SAT", "TONE", "RAW", "VIB"),
    ("TONE", "RAW", "VIB", "SAT"),
)
SAT_COMPARISON_GROUPS = (
    ("RAW", "SAT-H", "SAT-X1", "SAT-X2"),
    ("RAW", "SAT-H", "SAT-X3", "SAT-X4"),
)
EXTENDED_SAT_ALIASES = frozenset(("SAT-X1", "SAT-X2", "SAT-X3", "SAT-X4"))
SCHEMA_VERSION = "inky133-color-calibration-1.0"


class CalibrationError(RuntimeError):
    """Invalid or unavailable pre-rendered calibration data."""


@dataclass(slots=True)
class CalibrationState:
    active: bool = False
    pattern_index: int = 0
    strength_index: int = 1
    source: str | None = None
    sat_comparison: bool = False
    sat_group_index: int = 0

    @property
    def pattern_number(self) -> int:
        return self.pattern_index + 1

    @property
    def pattern(self) -> tuple[str, str, str, str]:
        return PATTERNS[self.pattern_index]

    @property
    def strength(self) -> str:
        return STRENGTHS[self.strength_index]

    def enter(self, source: str) -> None:
        self.active = True
        self.pattern_index = 0
        self.strength_index = 1
        self.source = source
        self.sat_comparison = False
        self.sat_group_index = 0

    def next_pattern(self) -> None:
        if self.active:
            self.pattern_index = (self.pattern_index + 1) % len(PATTERNS)

    def select_source(self, source: str) -> None:
        if not self.active:
            raise CalibrationError("Calibration mode is not active")
        self.source = source
        self.pattern_index = 0

    def next_strength(self) -> None:
        if self.active:
            self.strength_index = (self.strength_index + 1) % len(STRENGTHS)

    def enter_sat_comparison(self) -> None:
        if not self.active:
            raise CalibrationError("Calibration mode is not active")
        self.sat_comparison = True
        self.sat_group_index = 0

    def exit_sat_comparison(self) -> None:
        self.sat_comparison = False
        self.sat_group_index = 0

    def next_sat_group(self) -> None:
        if self.active and self.sat_comparison:
            self.sat_group_index = (
                self.sat_group_index + 1
            ) % len(SAT_COMPARISON_GROUPS)

    def exit(self) -> None:
        self.active = False
        self.source = None


@dataclass(frozen=True, slots=True)
class CalibrationAssets:
    source: str
    variants: Mapping[str, Path]

    @property
    def supports_sat_comparison(self) -> bool:
        return EXTENDED_SAT_ALIASES.issubset(self.variants)


class ColorCalibrationCatalog:
    def __init__(self, entries: Mapping[str, CalibrationAssets]) -> None:
        self.entries = dict(entries)
        self.sources = tuple(sorted(self.entries, key=str.casefold))

    @classmethod
    def empty(cls) -> "ColorCalibrationCatalog":
        return cls({})

    @classmethod
    def load(cls, manifest_path: Path, root: Path) -> "ColorCalibrationCatalog":
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CalibrationError(f"Cannot read calibration manifest: {exc}") from exc
        if payload.get("schema_version") != SCHEMA_VERSION:
            raise CalibrationError("Unsupported calibration manifest")
        records = payload.get("entries")
        if not isinstance(records, dict):
            raise CalibrationError("Calibration manifest requires entries")
        resolved_root = root.resolve(strict=True)
        entries: dict[str, CalibrationAssets] = {}
        required = {"RAW"} | {
            f"{mode}-{strength}"
            for mode in MODES[1:]
            for strength in STRENGTHS
        }
        for source, record in records.items():
            if not isinstance(source, str) or not isinstance(record, dict):
                raise CalibrationError("Invalid calibration entry")
            variants = record.get("variants")
            if not isinstance(variants, dict) or not required.issubset(variants):
                raise CalibrationError(f"Incomplete calibration variants: {source}")
            aliases = set(variants)
            extended = aliases.intersection(EXTENDED_SAT_ALIASES)
            if extended and extended != EXTENDED_SAT_ALIASES:
                raise CalibrationError(
                    f"Incomplete extended SAT variants: {source}"
                )
            unknown = aliases - required - EXTENDED_SAT_ALIASES
            if unknown:
                raise CalibrationError(
                    f"Unknown calibration variants: {source}: {sorted(unknown)}"
                )
            paths: dict[str, Path] = {}
            for alias, relative in variants.items():
                if not isinstance(relative, str):
                    raise CalibrationError(f"Invalid calibration path: {source}/{alias}")
                try:
                    path = (resolved_root / relative).resolve(strict=True)
                    path.relative_to(resolved_root)
                except (OSError, ValueError) as exc:
                    raise CalibrationError(
                        f"Calibration path escapes or is missing: {source}/{alias}"
                    ) from exc
                paths[alias] = path
            entries[source] = CalibrationAssets(source=source, variants=paths)
        return cls(entries)

    def lookup(self, source: str) -> CalibrationAssets | None:
        return self.entries.get(source)

    def at(self, index: int) -> CalibrationAssets:
        if not self.sources:
            raise CalibrationError("Color calibration catalog is empty")
        return self.entries[self.sources[index % len(self.sources)]]

    def __len__(self) -> int:
        return len(self.sources)


def alias_for(mode: str, strength: str) -> str:
    return "RAW" if mode == "RAW" else f"{mode}-{strength}"


def labels_for(pattern_index: int, strength: str) -> tuple[str, ...]:
    return tuple(alias_for(mode, strength) for mode in PATTERNS[pattern_index])


def labels_for_state(state: CalibrationState) -> tuple[str, ...]:
    if state.sat_comparison:
        return SAT_COMPARISON_GROUPS[state.sat_group_index]
    return labels_for(state.pattern_index, state.strength)


def _font(font_path: str | Path | None, size: int) -> ImageFont.ImageFont:
    if font_path:
        try:
            return ImageFont.truetype(str(font_path), size)
        except OSError:
            pass
    return ImageFont.load_default()


def _validated_copy(path: Path) -> Image.Image:
    try:
        with Image.open(path) as opened:
            opened.load()
            if opened.format != "PNG" or opened.mode != "RGB" or opened.size != (WIDTH, HEIGHT):
                raise CalibrationError(
                    f"Invalid calibration PNG {path}: "
                    f"format={opened.format}, mode={opened.mode}, size={opened.size}"
                )
            if opened.getpalette() is not None:
                raise CalibrationError(f"Calibration RGB unexpectedly has palette: {path}")
            return opened.copy()
    except OSError as exc:
        raise CalibrationError(f"Cannot load calibration PNG {path}: {exc}") from exc


def compose_calibration_image(
    assets: CalibrationAssets,
    state: CalibrationState,
    *,
    font_path: str | Path | None = None,
    draw_overlays: bool = True,
) -> Image.Image:
    if not state.active or state.source != assets.source:
        raise CalibrationError("Calibration state does not match assets")
    result = Image.new("RGB", (WIDTH, HEIGHT), "white")
    labels = labels_for_state(state)
    for stripe, alias in enumerate(labels):
        path = assets.variants.get(alias)
        if path is None:
            raise CalibrationError(
                f"Calibration variant is unavailable: {assets.source}/{alias}"
            )
        source = _validated_copy(path)
        x0 = stripe * STRIPE_WIDTH
        x1 = x0 + STRIPE_WIDTH
        result.paste(source.crop((x0, 0, x1, HEIGHT)), (x0, 0))
    if not draw_overlays:
        return result

    draw = ImageDraw.Draw(result)
    label_font = _font(font_path, 24)
    status_font = _font(font_path, 18)
    for stripe, label in enumerate(labels):
        x = stripe * STRIPE_WIDTH + 12
        y = 12
        box = draw.textbbox((x, y), label, font=label_font)
        draw.rectangle((box[0] - 7, box[1] - 5, box[2] + 7, box[3] + 5), fill="white")
        draw.text((x, y), label, font=label_font, fill="black")
    if state.sat_comparison:
        status = f"CAL SAT-{state.sat_group_index + 1}"
    else:
        status = f"CAL P{state.pattern_number} {state.strength}"
    box = draw.textbbox((0, 0), status, font=status_font)
    width = box[2] - box[0]
    height = box[3] - box[1]
    x = WIDTH - width - 14
    y = HEIGHT - height - 14
    draw.rectangle((x - 7, y - 5, x + width + 7, y + height + 5), fill="white")
    draw.text((x - box[0], y - box[1]), status, font=status_font, fill="black")
    return result
