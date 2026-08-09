#!/usr/bin/env python3

from PIL import Image
from inky.auto import auto

print("1. Initializing display...", flush=True)
inky = auto(verbose=True)

print(
    f"2. Display detected: {inky.width}x{inky.height}",
    flush=True,
)

img = Image.open("display-test-chart.png").convert("RGB")

print(
    f"3. Image loaded: {img.size} / {img.mode}",
    flush=True,
)

print("4. Calling set_image()...", flush=True)
inky.set_image(img)
print("5. set_image() finished.", flush=True)

print("6. Calling show()...", flush=True)
inky.show()
print("7. show() finished.", flush=True)
