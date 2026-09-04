"""Indexed access to Mac-generated ``metadata.json``."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping


logger = logging.getLogger("inky_slideshow")


@dataclass(frozen=True)
class PhotoMetadata:
    date: datetime | None
    source: str | None
    display_mode: str
    raw: Mapping[str, Any]


def parse_capture_date(value: object) -> datetime | None:
    """Parse the date formats emitted by the Mac pipeline."""

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


class MetadataIndex:
    """Build O(1) filename indexes once at startup."""

    def __init__(self, entries: Mapping[str, Any] | None = None) -> None:
        self._entries: dict[str, Mapping[str, Any]] = {}
        self._by_filename: dict[str, Mapping[str, Any]] = {}

        for key, value in (entries or {}).items():
            if not isinstance(value, Mapping):
                continue
            self._entries[str(key)] = value
            names = {Path(str(key)).name}
            for field in ("output", "output_name", "filename"):
                field_value = value.get(field)
                if field_value:
                    names.add(Path(str(field_value)).name)
            for name in names:
                self._by_filename.setdefault(name, value)

    @classmethod
    def load(cls, path: Path) -> "MetadataIndex":
        if not path.exists():
            logger.warning("Metadata file not found: %s", path)
            return cls()
        try:
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
            if not isinstance(data, dict):
                raise ValueError("metadata root must be a JSON object")
        except Exception:
            logger.exception("Failed to load metadata: %s", path)
            return cls()
        logger.info("Metadata loaded: %d entries", len(data))
        return cls(data)

    def __len__(self) -> int:
        return len(self._entries)

    def raw_entry(self, image_path: str | Path) -> Mapping[str, Any] | None:
        return self._by_filename.get(Path(image_path).name)

    def lookup(self, image_path: str | Path) -> PhotoMetadata | None:
        entry = self.raw_entry(image_path)
        if entry is None:
            return None

        classification = entry.get("classification")
        if not isinstance(classification, Mapping):
            classification = {}

        display_mode = str(
            entry.get("display_mode")
            or entry.get("mode")
            or classification.get("display_mode")
            or "unknown"
        )
        source = entry.get("source")
        return PhotoMetadata(
            date=parse_capture_date(entry.get("capture_date") or entry.get("date")),
            source=str(source) if source is not None else None,
            display_mode=display_mode,
            raw=entry,
        )
