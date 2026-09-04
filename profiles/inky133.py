"""Inky Impression 13.3-inch Spectra 6 profile."""

from .model import (
    ButtonConfiguration,
    OverlayDefaults,
    Profile,
    RefreshBehavior,
)


PROFILE = Profile(
    key="inky133",
    display_name='Inky Impression 13.3" Spectra 6',
    width=1600,
    height=1200,
    input_mode="RGB",
    display_driver="inky.auto:auto",
    refresh=RefreshBehavior(method="show", full_refresh=True),
    buttons=ButtonConfiguration(
        next_gpio=5,
        system_gpio=6,
        bounce_time=0.08,
        poweroff_hold_seconds=3.0,
    ),
    # These values are copied from the production 13.3-inch slideshow.
    overlay=OverlayDefaults(
        font_size=20,
        date_font_size=24,
        positions=(
            "bottom-right",
            "top-right",
            "top-left",
            "bottom-left",
        ),
        margin=25,
        background_padding=15,
        text_padding=12,
        line_spacing=8,
    ),
    image_directory="photos/auto",
    metadata_path="photos/metadata.json",
    default_interval=1800,
    hostname="wc-inky133",
    state_suffix="133",
)
