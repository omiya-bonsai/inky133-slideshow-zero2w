#!/usr/bin/env python3
from PIL import Image
import piexif
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
RAW_DIR = os.path.join(BASE_DIR, "photos_raw")
OUT_DIR = os.path.join(BASE_DIR, "photos")

TARGET_SIZE = (1600, 1200)  # (width, height)

os.makedirs(OUT_DIR, exist_ok=True)


def process_one(path_in, path_out):
    with Image.open(path_in) as img:
        # 元画像の EXIF を退避（JPEG の場合に入っていることが多い）
        exif_bytes = img.info.get("exif")

        img = img.convert("RGB")
        w, h = img.size
        tw, th = TARGET_SIZE
        img_ratio = w / h
        target_ratio = tw / th

        # アスペクト比を維持しつつ、長辺基準で縮小
        if img_ratio > target_ratio:
            # 横長 → 高さに合わせて縮小
            new_height = th
            new_width = int(th * img_ratio)
        else:
            # 縦長 → 幅に合わせて縮小
            new_width = tw
            new_height = int(tw / img_ratio)

        img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        # 中央トリミング
        left = (new_width - tw) // 2
        top = (new_height - th) // 2
        img = img.crop((left, top, left + tw, top + th))

        # EXIF がある場合はそれも一緒に書き戻す
        if exif_bytes:
            try:
                img.save(
                    path_out,
                    format="JPEG",
                    quality=90,
                    optimize=True,
                    exif=exif_bytes,
                )
            except TypeError:
                # もし古い Pillow などで exif 引数が使えなければ、EXIF なしで保存
                img.save(path_out, format="JPEG", quality=90, optimize=True)
        else:
            img.save(path_out, format="JPEG", quality=90, optimize=True)

        print(f"OK: {os.path.basename(path_out)}")


def main():
    for name in sorted(os.listdir(RAW_DIR)):
        if not name.lower().endswith((".jpg", ".jpeg", ".png")):
            continue
        src = os.path.join(RAW_DIR, name)
        dst = os.path.join(OUT_DIR, os.path.splitext(name)[0] + ".jpeg")
        process_one(src, dst)


if __name__ == "__main__":
    main()
