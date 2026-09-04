"""Validated effect metadata and weighted ticket generation."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


SCHEMA_VERSION = "inky133-apple-effects-metadata-1.0"
BASE_WEIGHT = 0.625


class CatalogError(RuntimeError):
    pass


def parse_capture_date(value: object) -> datetime | None:
    """Parse capture dates without depending on either repository's metadata module."""

    if not value:
        return None
    candidate = str(value).strip()[:19]
    for date_format in (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    ):
        try:
            return datetime.strptime(candidate, date_format)
        except ValueError:
            continue
    return None


@dataclass(frozen=True, slots=True)
class EffectEntry:
    path: Path
    relative_output: str
    source: str
    category: str
    display_mode: str
    capture_date: object
    weight: float
    fallback: bool
    vision_person_detected: bool
    vision_face_count: int
    raw: dict[str, object]


class EffectCatalog:
    def __init__(self, entries: list[EffectEntry]) -> None:
        if not entries:
            raise CatalogError("Effect metadata contains no entries")
        self.entries = entries
        self.by_path = {str(entry.path): entry for entry in entries}

    @classmethod
    def load(cls, metadata_path: Path, library_root: Path) -> "EffectCatalog":
        try:
            payload = json.loads(metadata_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CatalogError(f"Cannot read effect metadata: {metadata_path}: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("schema_version") != SCHEMA_VERSION:
            raise CatalogError("Unsupported effect metadata schema")
        records = payload.get("entries")
        if not isinstance(records, dict):
            raise CatalogError("Effect metadata requires an entries object")
        root = library_root.resolve(strict=True)
        entries: list[EffectEntry] = []
        for key, record in records.items():
            if not isinstance(key, str) or not isinstance(record, dict):
                raise CatalogError("Invalid effect metadata entry")
            try:
                path = (root / key).resolve(strict=True)
                path.relative_to(root)
            except (OSError, ValueError) as exc:
                raise CatalogError(f"Effect output escapes or is missing: {key}") from exc
            if not path.is_file() or path.suffix.lower() != ".png":
                raise CatalogError(f"Effect output is not PNG: {key}")
            source = record.get("source")
            category = record.get("category")
            mode = record.get("display_mode")
            weight = record.get("weight")
            if not isinstance(source, str) or category not in {"photo", "illustration"}:
                raise CatalogError(f"Invalid source/category: {key}")
            if not isinstance(mode, str) or not mode:
                raise CatalogError(f"Missing display mode: {key}")
            if not isinstance(weight, (int, float)) or weight <= 0:
                raise CatalogError(f"Invalid weight: {key}")
            entries.append(
                EffectEntry(
                    path=path,
                    relative_output=key,
                    source=source,
                    category=category,
                    display_mode=mode,
                    capture_date=parse_capture_date(record.get("capture_date")),
                    weight=float(weight),
                    fallback=bool(record.get("fallback")),
                    vision_person_detected=bool(record.get("vision_person_detected")),
                    vision_face_count=int(record.get("vision_face_count", 0)),
                    raw=record,
                )
            )
        return cls(entries)

    def weighted_tickets(self) -> list[str]:
        tickets: list[str] = []
        for entry in self.entries:
            count = max(1, round(entry.weight / BASE_WEIGHT))
            tickets.extend([str(entry.path)] * count)
        return tickets

    def lookup(self, path: str | Path) -> EffectEntry:
        try:
            return self.by_path[str(Path(path).resolve(strict=True))]
        except (OSError, KeyError) as exc:
            raise CatalogError(f"Image is not indexed by effect metadata: {path}") from exc
