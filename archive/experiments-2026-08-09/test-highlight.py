#!/usr/bin/env python3

from PIL import Image
from inky.auto import auto


IMAGE_PATH = "photos/photo/808.jpeg"

SATURATION = 0.75

# この値より明るい領域だけを圧縮する
HIGHLIGHT_KNEE = 180

# 大きいほどハイライト圧縮が強くなる
HIGHLIGHT_STRENGTH = 48


def compress_highlights(img):
    """
    暗部・中間調はほぼそのままにして、
    明るい領域だけを緩やかに圧縮する。

    純白 (255) は 255 のまま維持する。
    """

    knee = HIGHLIGHT_KNEE
    strength = HIGHLIGHT_STRENGTH
    span = 255 - knee

    lut = []

    for value in range(256):
        if value <= knee:
            output = value
        else:
            t = (value - knee) / span

            # 中高輝度域を下げるが、
            # 255では再び255になる滑らかなカーブ
            reduction = strength * t * (1.0 - t)
            output = round(value - reduction)

        lut.append(max(0, min(255, output)))

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

        # 今回追加する唯一の画像補正
        img = compress_highlights(img)

    print(f"Image              : {IMAGE_PATH}")
    print(f"Resolution         : {img.size}")
    print("Contrast           : 1.00")
    print("Brightness         : 1.00")
    print(f"Saturation         : {SATURATION}")
    print(f"Highlight knee     : {HIGHLIGHT_KNEE}")
    print(f"Highlight strength : {HIGHLIGHT_STRENGTH}")

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
