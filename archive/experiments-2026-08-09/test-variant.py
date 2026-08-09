#!/usr/bin/env python3

import sys
from pathlib import Path

from PIL import Image
from inky.auto import auto


BASE_DIR = Path(
    "/home/bonsai/inky133-slideshow/tmp/variant-test"
)

FILENAME = "-1272204690239012361_IMG_0032__e6c08429.png"

VALID_MODES = {
    "color",
    "monochrome",
    "sepia",
}


def main():
    if len(sys.argv) != 2:
        raise SystemExit(
            "Usage: python3 test-variant.py "
            "{color|monochrome|sepia}"
        )

    mode = sys.argv[1].lower()

    if mode not in VALID_MODES:
        raise SystemExit(
            f"Unknown mode: {mode}"
        )

    path = BASE_DIR / mode / FILENAME

    if not path.exists():
        raise SystemExit(
            f"Image not found: {path}"
        )

    inky = auto(verbose=True)

    img = Image.open(path)

    print(f"Mode            : {mode}")
    print(f"Image mode      : {img.mode}")
    print(f"Resolution      : {img.size}")

    if img.mode != "P":
        raise SystemExit(
            "ERROR: expected P-mode PNG"
        )

    if img.palette is None:
        raise SystemExit(
            "ERROR: palette missing"
        )

    print(
        f"Palette colours : "
        f"{len(img.palette.colors)}"
    )

    inky.set_image(img)
    inky.show()

    print("Finished.")


if __name__ == "__main__":
    main()
