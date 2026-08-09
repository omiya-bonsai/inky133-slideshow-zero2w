#!/usr/bin/env python3

from PIL import Image
from inky.auto import auto


IMAGE_PATH = "photos/photo/808.jpeg"

SATURATION = 0.72
GAMMA = 1.25


def apply_gamma(img, gamma):
    """
    gamma > 1.0:
      中間調～明部を少し暗くする。
      Spectra 6での白飛び抑制を狙う。
    """
    lut = [
        max(
            0,
            min(
                255,
                round(((i / 255.0) ** gamma) * 255)
            )
        )
        for i in range(256)
    ]

    return img.point(lut * 3)


def main():
    print("Initializing Inky...")
    inky = auto(verbose=True)

    with Image.open(IMAGE_PATH) as src:
        img = src.convert("RGB")

        img = img.resize(
            (inky.width, inky.height),
            Image.Resampling.LANCZOS,
        )

        img = apply_gamma(img, GAMMA)

    print(f"Image      : {IMAGE_PATH}")
    print(f"Resolution : {img.size}")
    print("Contrast   : 1.00")
    print("Brightness : 1.00")
    print(f"Gamma      : {GAMMA}")
    print(f"Saturation : {SATURATION}")

    print("Sending image...")

    inky.set_image(
        img,
        saturation=SATURATION,
    )

    print("Refreshing display...")
    inky.show()

    print("Finished.")


if __name__ == "__main__":
    main()
