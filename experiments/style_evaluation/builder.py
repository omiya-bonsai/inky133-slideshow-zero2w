"""Build a completely isolated Inky133 style-evaluation library."""

from __future__ import annotations

import hashlib
import json
from concurrent.futures import ProcessPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Iterable, Mapping

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

import config
from experiments.illustrated_photo.renderer import (
    DISPLAY_SIZE,
    MASK_CORE_THRESHOLD,
    build_skin_masks,
    load_presets,
    style_person,
    validate_output_image,
)
from inky133_renderer import DEFAULT_FEATHER_RADIUS, render_inky133_photo
from metadata import load_metadata, save_metadata
from person_mask import PersonMaskProvider, VisionPersonMaskProvider
from pipeline import Pipeline, SourceImage, output_name, save_png_atomic
from preprocess import normalize_source, render_color
from profiles import load_profile


STYLE_BUILD_VERSION = "1.0"
STYLE_KEYS = ("classic", "illustrated", "poster", "vintage", "watercolor")
DEFAULT_OUTPUT_ROOT = config.OUTPUT_DIR / "experiments/inky133-style-evaluation"
DEFAULT_STYLE_FILE = Path(__file__).with_name("styles.json")


class StyleBuildError(RuntimeError):
    """A user-facing style-library validation or build error."""


@dataclass(frozen=True, slots=True)
class StyleDefinition:
    key: str
    label: str
    engine: str
    description: str
    parameters: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class BuildSummary:
    sources: int
    rendered: int
    skipped: int
    failed: int
    output_root: Path


def load_style_definitions(path: Path = DEFAULT_STYLE_FILE) -> dict[str, StyleDefinition]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise StyleBuildError(f"Cannot read style definitions: {path}: {exc}") from exc
    if not isinstance(payload, dict) or tuple(payload) != STYLE_KEYS:
        raise StyleBuildError(f"Style definitions must be ordered as {STYLE_KEYS}")
    result: dict[str, StyleDefinition] = {}
    valid_engines = {"classic", "illustrated_preset", "vintage", "watercolor"}
    for key, value in payload.items():
        if not isinstance(value, dict):
            raise StyleBuildError(f"Invalid style definition: {key}")
        label = value.get("label")
        engine = value.get("engine")
        description = value.get("description")
        if not all(isinstance(item, str) and item for item in (label, engine, description)):
            raise StyleBuildError(f"Style {key} has incomplete identity fields")
        if engine not in valid_engines:
            raise StyleBuildError(f"Style {key} uses unsupported engine {engine!r}")
        parameters = {
            parameter: setting
            for parameter, setting in value.items()
            if parameter not in {"label", "engine", "description"}
        }
        result[key] = StyleDefinition(key, label, engine, description, parameters)
    return result


def _config_digest(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(STYLE_BUILD_VERSION.encode("utf-8"))
    digest.update(path.read_bytes())
    return digest.hexdigest()


def _weighted_mask(mask: Image.Image, strength: float) -> Image.Image:
    values = np.asarray(mask, dtype=np.float32) * strength
    return Image.fromarray(np.rint(np.clip(values, 0, 255)).astype(np.uint8), "L")


def _person_only(styled: Image.Image, source: Image.Image, mask: Image.Image) -> Image.Image:
    binary = mask.point(lambda value: 255 if value >= MASK_CORE_THRESHOLD else 0)
    return Image.composite(styled, source, binary)


def _render_with_classic_background(
    original: Image.Image,
    styled: Image.Image,
    feathered_mask: Image.Image,
    classic: Image.Image,
    palette: tuple[tuple[int, int, int], ...],
) -> Image.Image:
    """Reuse Classic's exact background indexes instead of re-quantizing it."""
    grayscale = ImageOps.grayscale(original).convert("RGB")
    composite = Image.composite(styled, grayscale, feathered_mask)
    colour = render_color(composite, palette)
    indexes = np.asarray(colour, dtype=np.uint8).copy()
    classic_indexes = np.asarray(classic, dtype=np.uint8)
    active = np.asarray(feathered_mask, dtype=np.uint8) > 0
    indexes[~active] = classic_indexes[~active]
    result = Image.fromarray(indexes, "P")
    result.putpalette(colour.getpalette())
    return result


def _vintage_person(
    source: Image.Image,
    person_mask: Image.Image,
    skin_mask: Image.Image,
    definition: StyleDefinition,
    palette: tuple[tuple[int, int, int], ...],
) -> Image.Image:
    saturation = float(definition.parameters["saturation"])
    contrast = float(definition.parameters["contrast"])
    strength = float(definition.parameters["pure_colour_strength"])
    protected = float(definition.parameters["skin_protection"])
    muted = ImageEnhance.Color(source).enhance(saturation)
    muted = ImageEnhance.Contrast(muted).enhance(contrast)
    rgb = np.asarray(source, dtype=np.uint8)
    hsv = np.asarray(source.convert("HSV"), dtype=np.uint8)
    hue = hsv[:, :, 0].astype(np.float32) * (360.0 / 255.0)
    sat = hsv[:, :, 1].astype(np.float32) / 255.0
    value = hsv[:, :, 2].astype(np.float32) / 255.0
    luminance = (
        0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]
    ) / 255.0
    indexes = np.where(luminance >= 0.60, 1, 0).astype(np.uint8)
    chromatic = (sat >= 0.10) & (value > 0.18)
    red = chromatic & ((hue < 24.0) | (hue >= 320.0))
    yellow = chromatic & (hue >= 24.0) & (hue < 185.0)
    indexes[red] = 3
    indexes[yellow] = 2
    target = Image.fromarray(np.asarray(palette, dtype=np.uint8)[indexes], "RGB")
    vintage = Image.blend(muted, target, strength)
    skin = ImageEnhance.Color(source).enhance(0.78)
    skin = ImageEnhance.Contrast(skin).enhance(0.96)
    vintage = Image.composite(skin, vintage, _weighted_mask(skin_mask, protected))
    return _person_only(vintage, source, person_mask)


def _watercolor_person(
    source: Image.Image,
    person_mask: Image.Image,
    skin_mask: Image.Image,
    definition: StyleDefinition,
) -> Image.Image:
    median_size = int(definition.parameters["median_size"])
    radius = float(definition.parameters["blur_radius"])
    saturation = float(definition.parameters["saturation"])
    contrast = float(definition.parameters["contrast"])
    protected = float(definition.parameters["skin_protection"])
    soft = source.filter(ImageFilter.MedianFilter(median_size)).filter(
        ImageFilter.GaussianBlur(radius)
    )
    soft = ImageEnhance.Color(soft).enhance(saturation)
    soft = ImageEnhance.Contrast(soft).enhance(contrast)
    skin = source.filter(ImageFilter.GaussianBlur(0.45))
    skin = ImageEnhance.Color(skin).enhance(0.90)
    soft = Image.composite(skin, soft, _weighted_mask(skin_mask, protected))
    return _person_only(soft, source, person_mask)


class StyleLibraryBuilder:
    """Incrementally build five styles without touching production paths."""

    def __init__(
        self,
        *,
        original_dir: Path = config.ORIGINAL_DIR,
        output_root: Path = DEFAULT_OUTPUT_ROOT,
        provider: PersonMaskProvider | None = None,
        normalizer: Callable[[Path, int, int], Image.Image] = normalize_source,
        style_file: Path = DEFAULT_STYLE_FILE,
        feather_radius: float = DEFAULT_FEATHER_RADIUS,
    ) -> None:
        self.original_dir = original_dir
        self.output_root = output_root
        self.styles_root = output_root / "styles"
        self.metadata_file = output_root / "metadata.json"
        self.provider = provider or VisionPersonMaskProvider()
        self.normalizer = normalizer
        self.style_file = style_file
        self.styles = load_style_definitions(style_file)
        self.style_digest = _config_digest(style_file)
        self.feather_radius = feather_radius
        self.profile = load_profile("inky133")
        self.illustrated_presets = load_presets()

    def collect_sources(self) -> list[SourceImage]:
        pipeline = Pipeline(self.profile, original_dir=self.original_dir)
        return [source for source in pipeline.collect_sources() if source.kind == "photo"]

    def _source_state(self, source: SourceImage, definition: StyleDefinition) -> dict[str, object]:
        stat = source.path.stat()
        return {
            "source": source.relative_path.as_posix(),
            "source_size": stat.st_size,
            "source_mtime_ns": stat.st_mtime_ns,
            "style_key": definition.key,
            "style": definition.label,
            "style_build_version": STYLE_BUILD_VERSION,
            "style_config_sha256": self.style_digest,
            "width": DISPLAY_SIZE[0],
            "height": DISPLAY_SIZE[1],
            "output_mode": "P",
        }

    def _is_current(self, destination: Path, old: Mapping[str, object] | None, state: Mapping[str, object]) -> bool:
        return destination.is_file() and old is not None and all(old.get(key) == value for key, value in state.items())

    def _render_styles(self, normalized: Image.Image) -> tuple[dict[str, Image.Image], dict[str, object]]:
        baseline = render_inky133_photo(
            normalized,
            self.profile.palette,
            self.provider,
            feather_radius=self.feather_radius,
        )
        images = {"classic": baseline.image}
        if not baseline.person_detected:
            for key in STYLE_KEYS[1:]:
                images[key] = baseline.image.copy()
            for key, image in images.items():
                validate_output_image(image, self.profile.palette, key)
            return images, {
                "segmentation_status": baseline.segmentation_status,
                "mask_coverage": baseline.mask_coverage,
                "person_instance_count": baseline.person_instance_count,
                "warning": baseline.warning,
            }
        skin_mask, _non_skin = build_skin_masks(normalized, baseline.person_mask)
        def render_one(key: str) -> Image.Image:
            definition = self.styles[key]
            if definition.engine == "illustrated_preset":
                preset_name = str(definition.parameters["preset"])
                styled, _stats = style_person(
                    normalized,
                    baseline.person_mask,
                    skin_mask,
                    self.illustrated_presets[preset_name],
                    self.profile.palette,
                )
            elif definition.engine == "vintage":
                styled = _vintage_person(
                    normalized,
                    baseline.person_mask,
                    skin_mask,
                    definition,
                    self.profile.palette,
                )
            elif definition.engine == "watercolor":
                styled = _watercolor_person(normalized, baseline.person_mask, skin_mask, definition)
            else:
                raise StyleBuildError(f"Unexpected style engine for {key}: {definition.engine}")
            return _render_with_classic_background(
                normalized,
                styled,
                baseline.feathered_mask,
                baseline.image,
                self.profile.palette,
            )

        for key in STYLE_KEYS[1:]:
            images[key] = render_one(key)
        for key, image in images.items():
            validate_output_image(image, self.profile.palette, key)
        return images, {
            "segmentation_status": baseline.segmentation_status,
            "mask_coverage": baseline.mask_coverage,
            "person_instance_count": baseline.person_instance_count,
            "warning": baseline.warning,
        }

    def build(
        self,
        sources: Iterable[SourceImage] | None = None,
        *,
        force: bool = False,
        dry_run: bool = False,
    ) -> BuildSummary:
        selected = list(sources if sources is not None else self.collect_sources())
        old_root = load_metadata(self.metadata_file)
        old_entries = old_root.get("entries", {}) if isinstance(old_root.get("entries"), dict) else {}
        entries = dict(old_entries)
        rendered_count = skipped_count = failed_count = 0
        if not dry_run:
            for key in STYLE_KEYS:
                (self.styles_root / key).mkdir(parents=True, exist_ok=True)
        total_sources = len(selected)
        for source_index, source in enumerate(selected, start=1):
            filename = output_name(source)
            states = {key: self._source_state(source, self.styles[key]) for key in STYLE_KEYS}
            destinations = {key: self.styles_root / key / filename for key in STYLE_KEYS}
            entry_keys = {key: f"styles/{key}/{filename}" for key in STYLE_KEYS}
            pending = [
                key for key in STYLE_KEYS
                if force or not self._is_current(destinations[key], old_entries.get(entry_keys[key]), states[key])
            ]
            skipped_count += len(STYLE_KEYS) - len(pending)
            if not pending:
                print(
                    f"SKIP    [{source_index}/{total_sources}] "
                    f"{source.relative_path.as_posix()}"
                )
                continue
            if dry_run:
                print(
                    f"PROCESS [{source_index}/{total_sources}] "
                    f"{source.relative_path.as_posix()} ({len(pending)} styles)"
                )
                rendered_count += len(pending)
                continue
            try:
                print(
                    f"PROCESS [{source_index}/{total_sources}] "
                    f"{source.relative_path.as_posix()} ({len(pending)} styles)",
                    flush=True,
                )
                normalized = self.normalizer(source.path, *DISPLAY_SIZE).convert("RGB")
                if normalized.size != DISPLAY_SIZE:
                    raise StyleBuildError(f"Normalizer returned {normalized.size} for {source.path}")
                images, segmentation = self._render_styles(normalized)
                built_at = datetime.now().astimezone().isoformat(timespec="seconds")
                for key in pending:
                    destination = destinations[key]
                    save_png_atomic(images[key], destination)
                    entry = {
                        **states[key],
                        "rendered": entry_keys[key],
                        "rendered_image": filename,
                        "built_at": built_at,
                        **segmentation,
                    }
                    entries[entry_keys[key]] = entry
                    rendered_count += 1
                save_metadata(
                    {
                        "schema_version": 1,
                        "profile": "inky133",
                        "purpose": "style_evaluation",
                        "styles": [self.styles[key].label for key in STYLE_KEYS],
                        "entries": entries,
                    },
                    self.metadata_file,
                )
            except Exception as exc:
                failed_count += len(pending)
                print(f"FAILED  {source.relative_path}: {exc}", flush=True)
        return BuildSummary(len(selected), rendered_count, skipped_count, failed_count, self.output_root)

    def build_parallel(
        self,
        sources: Iterable[SourceImage] | None = None,
        *,
        force: bool = False,
        workers: int = 4,
    ) -> BuildSummary:
        """Build independent source photos in worker processes; metadata stays serialized."""
        if workers < 1:
            raise ValueError("workers must be at least 1")
        if workers == 1:
            return self.build(sources, force=force)
        selected = list(sources if sources is not None else self.collect_sources())
        old_root = load_metadata(self.metadata_file)
        old_entries = (
            old_root.get("entries", {})
            if isinstance(old_root.get("entries"), dict)
            else {}
        )
        entries = dict(old_entries)
        for key in STYLE_KEYS:
            (self.styles_root / key).mkdir(parents=True, exist_ok=True)
        tasks: list[tuple[SourceImage, tuple[str, ...], dict[str, dict[str, object]]]] = []
        skipped_count = 0
        total_sources = len(selected)
        for source_index, source in enumerate(selected, start=1):
            filename = output_name(source)
            states = {
                key: self._source_state(source, self.styles[key]) for key in STYLE_KEYS
            }
            destinations = {
                key: self.styles_root / key / filename for key in STYLE_KEYS
            }
            entry_keys = {
                key: f"styles/{key}/{filename}" for key in STYLE_KEYS
            }
            pending = tuple(
                key
                for key in STYLE_KEYS
                if force
                or not self._is_current(
                    destinations[key], old_entries.get(entry_keys[key]), states[key]
                )
            )
            skipped_count += len(STYLE_KEYS) - len(pending)
            if not pending:
                print(
                    f"SKIP    [{source_index}/{total_sources}] "
                    f"{source.relative_path.as_posix()}"
                )
                continue
            print(
                f"QUEUE   [{source_index}/{total_sources}] "
                f"{source.relative_path.as_posix()} ({len(pending)} styles)"
            )
            tasks.append((source, pending, states))

        rendered_count = failed_count = completed_sources = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(
                    _build_source_task,
                    source,
                    pending,
                    states,
                    self.output_root,
                    self.style_file,
                    self.feather_radius,
                ): (source, pending)
                for source, pending, states in tasks
            }
            for future in as_completed(futures):
                source, pending = futures[future]
                try:
                    delta = future.result()
                    entries.update(delta)
                    rendered_count += len(delta)
                    completed_sources += 1
                    save_metadata(
                        {
                            "schema_version": 1,
                            "profile": "inky133",
                            "purpose": "style_evaluation",
                            "styles": [self.styles[key].label for key in STYLE_KEYS],
                            "entries": entries,
                        },
                        self.metadata_file,
                    )
                    print(
                        f"DONE    [{completed_sources}/{len(tasks)}] "
                        f"{source.relative_path.as_posix()}",
                        flush=True,
                    )
                except Exception as exc:
                    failed_count += len(pending)
                    print(f"FAILED  {source.relative_path}: {exc}", flush=True)
        return BuildSummary(
            len(selected),
            rendered_count,
            skipped_count,
            failed_count,
            self.output_root,
        )


def _build_source_task(
    source: SourceImage,
    pending: tuple[str, ...],
    states: dict[str, dict[str, object]],
    output_root: Path,
    style_file: Path,
    feather_radius: float,
) -> dict[str, dict[str, object]]:
    """Worker entry point. Each process writes only its own unique PNG paths."""
    builder = StyleLibraryBuilder(
        output_root=output_root,
        style_file=style_file,
        feather_radius=feather_radius,
    )
    normalized = builder.normalizer(source.path, *DISPLAY_SIZE).convert("RGB")
    if normalized.size != DISPLAY_SIZE:
        raise StyleBuildError(
            f"Normalizer returned {normalized.size} for {source.path}"
        )
    images, segmentation = builder._render_styles(normalized)
    filename = output_name(source)
    built_at = datetime.now().astimezone().isoformat(timespec="seconds")
    delta: dict[str, dict[str, object]] = {}
    for key in pending:
        destination = builder.styles_root / key / filename
        save_png_atomic(images[key], destination)
        entry_key = f"styles/{key}/{filename}"
        delta[entry_key] = {
            **states[key],
            "rendered": entry_key,
            "rendered_image": filename,
            "built_at": built_at,
            **segmentation,
        }
    return delta
