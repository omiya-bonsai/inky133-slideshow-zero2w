#!/usr/bin/env python3

from PIL import Image, ImageDraw, ImageFont

WIDTH = 1600
HEIGHT = 1200
OUTPUT = "display-test-chart.png"

img = Image.new("RGB", (WIDTH, HEIGHT), "white")
draw = ImageDraw.Draw(img)

try:
    title_font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 42
    )
    label_font = ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 26
    )
except OSError:
    title_font = ImageFont.load_default()
    label_font = ImageFont.load_default()


def text_color(rgb):
    r, g, b = rgb
    luminance = 0.299 * r + 0.587 * g + 0.114 * b
    return "black" if luminance > 150 else "white"


def color_box(x1, y1, x2, y2, color, label):
    draw.rectangle((x1, y1, x2, y2), fill=color, outline="black", width=3)

    bbox = draw.textbbox((0, 0), label, font=label_font)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    tx = x1 + ((x2 - x1) - tw) // 2
    ty = y1 + ((y2 - y1) - th) // 2

    draw.text(
        (tx, ty),
        label,
        fill=text_color(color),
        font=label_font,
    )


draw.text(
    (50, 30),
    'Inky Impression 13.3" Display Test',
    fill="black",
    font=title_font,
)

# ============================================================
# 基本色
# ============================================================

colors = [
    ((255, 0, 0), "RED"),
    ((0, 255, 0), "GREEN"),
    ((0, 0, 255), "BLUE"),
    ((255, 255, 0), "YELLOW"),
    ((255, 128, 0), "ORANGE"),
    ((255, 255, 255), "WHITE"),
    ((0, 0, 0), "BLACK"),
    ((128, 128, 128), "GRAY"),
]

margin = 50
top = 110
gap = 10
box_w = (WIDTH - margin * 2 - gap * 3) // 4
box_h = 190

for i, (color, label) in enumerate(colors):
    row = i // 4
    col = i % 4

    x1 = margin + col * (box_w + gap)
    y1 = top + row * (box_h + gap)
    x2 = x1 + box_w
    y2 = y1 + box_h

    color_box(x1, y1, x2, y2, color, label)

# ============================================================
# グレースケール
# ============================================================

gray_top = 520

draw.text(
    (50, gray_top - 45),
    "Grayscale",
    fill="black",
    font=label_font,
)

steps = 16
gray_w = (WIDTH - 100) // steps

for i in range(steps):
    value = round(255 * i / (steps - 1))

    x1 = 50 + i * gray_w
    x2 = 50 + (i + 1) * gray_w
    y1 = gray_top
    y2 = gray_top + 150

    draw.rectangle(
        (x1, y1, x2, y2),
        fill=(value, value, value),
    )

# ============================================================
# 実写真で重要な色
# ============================================================

sample_top = 760

draw.text(
    (50, sample_top - 45),
    "Photo-oriented colours",
    fill="black",
    font=label_font,
)

samples = [
    ((235, 185, 150), "SKIN"),
    ((105, 160, 80), "FOLIAGE"),
    ((70, 130, 190), "SKY"),
    ((120, 75, 45), "WOOD"),
    ((180, 50, 80), "MAGENTA"),
    ((40, 60, 110), "NAVY"),
]

sample_gap = 10
sample_w = (WIDTH - 100 - sample_gap * 5) // 6

for i, (color, label) in enumerate(samples):
    x1 = 50 + i * (sample_w + sample_gap)
    y1 = sample_top
    x2 = x1 + sample_w
    y2 = y1 + 260

    color_box(x1, y1, x2, y2, color, label)

img.save(OUTPUT, "PNG")

print(f"Created: {OUTPUT}")
print(f"Size: {img.size}")
print(f"Mode: {img.mode}")
