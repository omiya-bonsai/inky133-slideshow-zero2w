"""Automatic profile discovery."""

from __future__ import annotations

import importlib
import pkgutil

from .model import Profile


def discover_profiles() -> dict[str, Profile]:
    profiles: dict[str, Profile] = {}

    for module_info in pkgutil.iter_modules(__path__):
        name = module_info.name
        if name.startswith("_") or name == "model":
            continue

        module = importlib.import_module(f"{__name__}.{name}")
        profile = getattr(module, "PROFILE", None)
        if not isinstance(profile, Profile):
            continue
        if profile.key in profiles:
            raise RuntimeError(f"Duplicate profile key: {profile.key}")
        profiles[profile.key] = profile

    # Largest display first keeps the established 13.3, 7.3, 5.7 order while
    # retaining automatic discovery for future profiles.
    ordered = sorted(profiles.values(), key=lambda item: (-item.width, item.key))
    return {profile.key: profile for profile in ordered}


def load_profile(name: str = "inky133") -> Profile:
    profiles = discover_profiles()
    try:
        return profiles[name]
    except KeyError as exc:
        choices = ", ".join(profiles) or "(none)"
        raise ValueError(
            f"Unknown profile {name!r}; available profiles: {choices}"
        ) from exc


def profile_names() -> tuple[str, ...]:
    return tuple(discover_profiles())


__all__ = ["Profile", "discover_profiles", "load_profile", "profile_names"]
