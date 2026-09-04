"""Runtime configuration and logging.

This is the only module that reads ``.env`` or process environment values.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from profiles.model import Profile


PROJECT_ROOT = Path(__file__).resolve().parent
DEFAULT_FONT_PATH = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


@dataclass(frozen=True)
class RuntimeConfig:
    profile: Profile
    project_root: Path
    image_directory: Path
    metadata_path: Path
    interval_seconds: int
    font_path: str
    state_file: Path
    counter_file: Path
    heartbeat_path: Path
    log_file: Path


def _profile_env(profile: Profile, name: str) -> str | None:
    return os.getenv(f"{profile.key.upper()}_{name}") or os.getenv(name)


def _resolve_path(value: str, project_root: Path) -> Path:
    path = Path(value).expanduser()
    if not path.is_absolute():
        path = project_root / path
    return path.resolve(strict=False)


def load_env_file(path: Path) -> None:
    """Load the small KEY=VALUE subset used by this project.

    Existing process environment values win, matching python-dotenv's
    ``override=False`` behaviour. This keeps Raspberry Pi dependencies small.
    """

    if not path.exists():
        return
    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ValueError(f"Invalid .env line {line_number}: {raw_line!r}")
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        os.environ.setdefault(key, value)


def load_config(
    profile: Profile,
    *,
    project_root: Path | None = None,
    env_file: Path | None = None,
) -> RuntimeConfig:
    root = (project_root or PROJECT_ROOT).resolve()
    load_env_file(env_file or root / ".env")

    image_directory = _resolve_path(
        _profile_env(profile, "PHOTO_DIR") or profile.image_directory,
        root,
    )
    metadata_path = _resolve_path(
        _profile_env(profile, "METADATA_FILE") or profile.metadata_path,
        root,
    )

    raw_interval = (
        _profile_env(profile, "INTERVAL_SECONDS")
        or str(profile.default_interval)
    )
    try:
        interval_seconds = int(raw_interval)
    except ValueError as exc:
        raise ValueError(
            f"INTERVAL_SECONDS must be an integer: {raw_interval!r}"
        ) from exc
    if interval_seconds <= 0:
        raise ValueError("INTERVAL_SECONDS must be positive")

    cache_dir = Path.home() / ".cache"
    logs_dir = Path.home() / ".logs"

    return RuntimeConfig(
        profile=profile,
        project_root=root,
        image_directory=image_directory,
        metadata_path=metadata_path,
        interval_seconds=interval_seconds,
        font_path=(
            _profile_env(profile, "FONT_PATH") or DEFAULT_FONT_PATH
        ),
        state_file=cache_dir / f"slideshow_state_{profile.state_suffix}.json",
        counter_file=logs_dir / f"slideshow_counter_{profile.state_suffix}.txt",
        # This path intentionally remains shared with the existing watchdog.
        heartbeat_path=Path("/tmp/inky_slideshow_heartbeat"),
        log_file=(
            logs_dir
            / "slideshow_logs"
            / f"slideshow_{profile.state_suffix}.log"
        ),
    )


def setup_logging(config: RuntimeConfig) -> logging.Logger:
    config.log_file.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(config.log_file),
            logging.StreamHandler(),
        ],
        force=True,
    )
    return logging.getLogger("inky_slideshow")
