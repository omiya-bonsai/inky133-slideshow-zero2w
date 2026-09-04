"""Inky Impression 5.7-inch seven-colour profile."""

from .model import (
    ButtonConfiguration,
    OverlayDefaults,
    Profile,
    RefreshBehavior,
)


PROFILE = Profile(
    key="inky57",
    display_name='Inky Impression 5.7" 7 Colour',
    width=600,
    height=448,
    input_mode="RGB",
    display_driver="inky.auto:auto",
    refresh=RefreshBehavior(method="show", full_refresh=True),
    buttons=ButtonConfiguration(),
    overlay=OverlayDefaults(
        font_size=12,
        date_font_size=15,
        positions=(
            "bottom-right",
            "top-right",
            "top-left",
            "bottom-left",
        ),
        margin=10,
        background_padding=7,
        text_padding=5,
        line_spacing=4,
    ),
    image_directory="photos/auto",
    metadata_path="photos/metadata.json",
    default_interval=1800,
    hostname="inky57",
    state_suffix="57",
)
