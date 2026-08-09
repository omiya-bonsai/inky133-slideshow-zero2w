#!/usr/bin/env python3

from PIL import Image
from inky.auto import auto

IMAGE_PATH = "photos/photo/808.jpeg"
SATURATION = 0.75

inky = auto(verbose=True)

with Image.open(IMAGE_PATH) as src:
    img = src.convert("RGB")

    img = img.resize(
        (inky.width, inky.height),
        Image.Resampling.LANCZOS,
    )

print(f"Image      : {IMAGE_PATH}")
print(f"Resolution : {img.size}")
print("Contrast   : 1.00 (no adjustment)")
print("Brightness : 1.00 (no adjustment)")
print(f"Saturation : {SATURATION}")

inky.set_image(
    img,
    saturation=SATURATION,
)

inky.show()

print("Finished.")
