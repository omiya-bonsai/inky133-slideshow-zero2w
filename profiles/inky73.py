"""Inky Impression 7.3-inch Spectra 6 profile."""

from .model import (
    ButtonConfiguration,
    OverlayDefaults,
    Profile,
    RefreshBehavior,
)


PROFILE = Profile(
    key="inky73",
    display_name='Inky Impression 7.3" Spectra 6',
    width=800,
    height=480,
    input_mode="RGB",
    display_driver="inky.auto:auto",
    refresh=RefreshBehavior(method="show", full_refresh=True),
    buttons=ButtonConfiguration(),
    overlay=OverlayDefaults(
        font_size=14,
        date_font_size=17,
        positions=(
            "bottom-right",
            "top-right",
            "top-left",
            "bottom-left",
        ),
        margin=12,
        background_padding=8,
        text_padding=6,
        line_spacing=4,
    ),
    image_directory="photos/auto",
    metadata_path="photos/metadata.json",
    default_interval=1800,
    hostname="inky73",
    state_suffix="73",
)
