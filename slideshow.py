#!/usr/bin/python3
"""
Pimoroni Inky Impression 13.3" Spectra 6 / 1600x1200 用 スライドショー

重要:
- Pillow側での強制6色減色はしない
- Inkyライブラリ側の色変換に任せる
- photos/photo/ と photos/art/ を再帰的に読む
"""

import os
import time
import random
import logging
import json
import subprocess
import threading
from datetime import datetime

from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import piexif
from dotenv import load_dotenv

load_dotenv()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.expanduser("~/.cache/slideshow_state_133.json")
COUNTER_FILE = os.path.expanduser("~/.logs/slideshow_counter_133.txt")
HEARTBEAT_PATH = "/tmp/inky_slideshow_heartbeat"

NEXT_IMAGE_EVENT = threading.Event()
BUTTON_B_PRESSED_AT = None

CONFIG = {
    "PHOTO_DIR": os.path.join(SCRIPT_DIR, os.getenv("PHOTO_DIR", "photos")),
    "FONT_PATH": os.getenv(
        "FONT_PATH",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
    "INTERVAL_SECONDS": int(os.getenv("INTERVAL_SECONDS", 1800)),
    "FONT_SIZE": 20,
    "DATE_FONT_SIZE": 24,
    "DATE_POSITIONS": ["bottom-right", "top-right", "top-left", "bottom-left"],
    "MARGIN": 25,
    "BACKGROUND_PADDING": 15,
    "TEXT_PADDING": 12,
    "LINE_SPACING": 8,

    "PHOTO_CONTRAST": 1.08,
    "PHOTO_BRIGHTNESS": 0.98,
    "ART_CONTRAST": 1.03,
    "ART_BRIGHTNESS": 1.00,
}

logger = None


def setup_logging():
    log_dir = os.path.expanduser("~/.logs/slideshow_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "slideshow_133.log")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    return logging.getLogger(__name__)


def initialize_display():
    possible_classes = [
        ("inky", "Inky"),
        ("inky.inky_impression", "InkyImpression"),
        ("inky.inky_el133uf1", "InkyEL133UF1"),
        ("inky.inky_impression", "InkyImpression133"),
        ("inky.auto", "auto"),
    ]

    for module_name, class_name in possible_classes:
        try:
            if class_name == "auto":
                from inky.auto import auto
                inky_display = auto()
            else:
                module = __import__(module_name, fromlist=[class_name])
                InkyClass = getattr(module, class_name)

                try:
                    inky_display = InkyClass(resolution=(1600, 1200))
                except TypeError:
                    inky_display = InkyClass()

            if hasattr(inky_display, "set_border"):
                inky_display.set_border(inky_display.WHITE)

            return inky_display

        except Exception:
            continue

    return create_dummy_display()


def create_dummy_display():
    class DummyDisplay:
        def __init__(self):
            self.width = 1600
            self.height = 1200
            self.WHITE = (255, 255, 255)

        def set_border(self, color):
            pass

        def set_image(self, image):
            pass

        def show(self):
            pass

    return DummyDisplay()


def setup_buttons():
    global BUTTON_B_PRESSED_AT

    try:
        from gpiozero import Button
    except Exception as e:
        logger.warning("gpiozero not available, buttons disabled: %s", e)
        return []

    btn_a = Button(5, pull_up=True, bounce_time=0.08)
    btn_b = Button(6, pull_up=True, bounce_time=0.08)

    def on_a_pressed():
        logger.info("Button A pressed: next image requested")
        NEXT_IMAGE_EVENT.set()

    def on_b_pressed():
        global BUTTON_B_PRESSED_AT
        BUTTON_B_PRESSED_AT = time.monotonic()
        logger.info("Button B pressed")

    def on_b_released():
        global BUTTON_B_PRESSED_AT

        if BUTTON_B_PRESSED_AT is None:
            return

        held = time.monotonic() - BUTTON_B_PRESSED_AT
        BUTTON_B_PRESSED_AT = None

        if held >= 3.0:
            logger.warning("Button B long press %.2fs: poweroff", held)
            subprocess.Popen(["sudo", "/usr/sbin/poweroff"])
        else:
            logger.warning("Button B short press %.2fs: reboot", held)
            subprocess.Popen(["sudo", "/usr/sbin/reboot"])

    btn_a.when_pressed = on_a_pressed
    btn_b.when_pressed = on_b_pressed
    btn_b.when_released = on_b_released

    logger.info("Buttons enabled: A=next, B=reboot, long-B=poweroff")
    return [btn_a, btn_b]


def save_state(queue, total_count):
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump({"total_count": total_count, "queue": queue}, f)
    except Exception:
        pass


def load_state():
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        return state.get("total_count", 0), state.get("queue", [])
    except Exception:
        return 0, []


def load_display_counter():
    try:
        with open(COUNTER_FILE, "r") as f:
            return int(f.read().strip())
    except Exception:
        return 0


def save_display_counter(counter: int):
    try:
        os.makedirs(os.path.dirname(COUNTER_FILE), exist_ok=True)
        with open(COUNTER_FILE, "w") as f:
            f.write(str(counter))
    except Exception:
        pass


def update_heartbeat():
    try:
        with open(HEARTBEAT_PATH, "w") as f:
            f.write(datetime.now().isoformat(timespec="minutes"))
    except Exception:
        pass


def get_system_uptime_seconds() -> int:
    try:
        with open("/proc/uptime", "r") as f:
            first = f.read().split()[0]
        return max(0, int(float(first)))
    except Exception:
        return 0


def format_uptime_htop(uptime_seconds: int) -> str:
    uptime_seconds = max(0, int(uptime_seconds))
    days, rem = divmod(uptime_seconds, 86400)
    hh, rem = divmod(rem, 3600)
    mm, ss = divmod(rem, 60)

    if days > 0:
        return f"{days} {'day' if days == 1 else 'days'}, {hh:02d}:{mm:02d}:{ss:02d}"

    return f"{hh:02d}:{mm:02d}:{ss:02d}"


def detect_image_mode(image_path: str) -> str:
    parts = os.path.normpath(image_path).lower().split(os.sep)

    if "art" in parts:
        return "art"

    if "photo" in parts:
        return "photo"

    return "photo"


def collect_images():
    image_paths = []

    for root, dirs, files in os.walk(CONFIG["PHOTO_DIR"]):
        dirs[:] = [d for d in dirs if not d.startswith(".")]

        for filename in files:
            if filename.startswith("."):
                continue

            if filename.lower().endswith((".jpg", ".jpeg", ".png")):
                image_paths.append(os.path.join(root, filename))

    return image_paths


def extract_capture_date(image_path):
    if image_path.lower().endswith(".png"):
        return None

    try:
        exif_dict = piexif.load(image_path)
        date_str = exif_dict["Exif"].get(piexif.ExifIFD.DateTimeOriginal)

        if date_str:
            return datetime.strptime(
                date_str.decode("utf-8"),
                "%Y:%m:%d %H:%M:%S",
            )
    except Exception:
        pass

    return None


def format_date_and_elapsed_time(capture_date):
    if not capture_date:
        return "Unknown date", "Unknown date", "Unknown date"

    now = datetime.now()
    formatted_date = capture_date.strftime("%Y-%m-%d")
    days = (now - capture_date).days

    if days >= 365:
        elapsed_text = f"{days // 365} years ago"
    elif days >= 30:
        elapsed_text = f"{days // 30} months ago"
    else:
        elapsed_text = "Within a month"

    if days >= 0:
        days_ago_text = f"{days} days ago (from today)"
    else:
        days_ago_text = f"{abs(days)} days from today"

    return formatted_date, elapsed_text, days_ago_text


def enhance_image(img, image_mode: str):
    if image_mode == "art":
        img = ImageEnhance.Contrast(img).enhance(CONFIG["ART_CONTRAST"])
        img = ImageEnhance.Brightness(img).enhance(CONFIG["ART_BRIGHTNESS"])
    else:
        img = ImageEnhance.Contrast(img).enhance(CONFIG["PHOTO_CONTRAST"])
        img = ImageEnhance.Brightness(img).enhance(CONFIG["PHOTO_BRIGHTNESS"])

    return img


def add_date_overlay(img, capture_date):
    draw = ImageDraw.Draw(img)

    try:
        font_small = ImageFont.truetype(CONFIG["FONT_PATH"], CONFIG["FONT_SIZE"])
        font_large = ImageFont.truetype(CONFIG["FONT_PATH"], CONFIG["DATE_FONT_SIZE"])
    except OSError:
        font_small = font_large = ImageFont.load_default()

    date_text, elapsed_text, days_ago_text = format_date_and_elapsed_time(capture_date)
    position = random.choice(CONFIG["DATE_POSITIONS"])

    margin = CONFIG["MARGIN"]
    padding = CONFIG["BACKGROUND_PADDING"]

    bbox1 = draw.textbbox((0, 0), date_text, font=font_large)
    bbox2 = draw.textbbox((0, 0), elapsed_text, font=font_small)
    bbox3 = draw.textbbox((0, 0), days_ago_text, font=font_small)

    width = max(
        bbox1[2] - bbox1[0],
        bbox2[2] - bbox2[0],
        bbox3[2] - bbox3[0],
    )

    h1 = bbox1[3] - bbox1[1]
    h2 = bbox2[3] - bbox2[1]
    h3 = bbox3[3] - bbox3[1]

    height = h1 + h2 + h3 + CONFIG["TEXT_PADDING"] * 2

    x = img.width - width - margin - padding if "right" in position else margin + padding
    y = img.height - height - margin - padding if "bottom" in position else margin + padding

    draw.rectangle(
        (x - padding, y - padding, x + width + padding, y + height + padding),
        fill="white",
    )

    draw.text((x, y), date_text, fill="black", font=font_large)

    y2 = y + h1 + CONFIG["TEXT_PADDING"]
    draw.text((x, y2), elapsed_text, fill="black", font=font_small)

    y3 = y2 + h2 + CONFIG["TEXT_PADDING"]
    draw.text((x, y3), days_ago_text, fill="black", font=font_small)

    return img, position


def add_status_overlay(img, date_position, slide_updated_at):
    draw = ImageDraw.Draw(img)

    try:
        font = ImageFont.truetype(CONFIG["FONT_PATH"], CONFIG["FONT_SIZE"])
    except OSError:
        font = ImageFont.load_default()

    updated_str = f"Updated: {slide_updated_at.strftime('%Y-%m-%d %H:%M')}"
    uptime_str = f"Uptime: {format_uptime_htop(get_system_uptime_seconds())}"
    text_block = f"{updated_str}\n{uptime_str}"

    opposite = {
        "bottom-right": "top-left",
        "top-right": "bottom-left",
        "top-left": "bottom-right",
        "bottom-left": "top-right",
    }.get(date_position, "bottom-left")

    margin = CONFIG["MARGIN"]
    padding = CONFIG["BACKGROUND_PADDING"]

    bbox = draw.multiline_textbbox(
        (0, 0),
        text_block,
        font=font,
        spacing=CONFIG["LINE_SPACING"],
    )

    width = bbox[2] - bbox[0]
    height = bbox[3] - bbox[1]

    x = img.width - width - margin - padding if "right" in opposite else margin + padding
    y = img.height - height - margin - padding if "bottom" in opposite else margin + padding

    draw.rectangle(
        (x - padding, y - padding, x + width + padding, y + height + padding),
        fill="white",
    )

    draw.multiline_text(
        (x, y),
        text_block,
        fill="black",
        font=font,
        spacing=CONFIG["LINE_SPACING"],
    )

    return img


def prepare_image(image_path, inky_display, slide_updated_at, counter):
    image_mode = detect_image_mode(image_path)

    with Image.open(image_path) as img:
        img = img.convert("RGB")
        img = enhance_image(img, image_mode)

        img = img.resize(
            (inky_display.width, inky_display.height),
            Image.Resampling.LANCZOS,
        )

        img, pos = add_date_overlay(img, extract_capture_date(image_path))
        img = add_status_overlay(img, pos, slide_updated_at)

        return img.convert("RGB")


def main():
    global logger

    inky = initialize_display()
    logger = setup_logging()
    buttons = setup_buttons()

    counter = load_display_counter()
    _, queue = load_state()

    while True:
        if not queue:
            queue = collect_images()

            if not queue:
                logger.error("No images found in %s", CONFIG["PHOTO_DIR"])
                time.sleep(60)
                continue

            random.shuffle(queue)
            logger.info("Image queue created: %d images", len(queue))

        image_path = queue.pop(0)

        if not os.path.exists(image_path):
            logger.warning("Missing image skipped: %s", image_path)
            save_state(queue, len(queue))
            continue

        counter += 1
        slide_updated_at = datetime.now()

        try:
            logger.info(
                "Displaying #%d: %s / mode=%s",
                counter,
                image_path,
                detect_image_mode(image_path),
            )

            img = prepare_image(image_path, inky, slide_updated_at, counter)

            inky.set_image(img)
            inky.show()

            save_display_counter(counter)
            save_state(queue, len(queue))
            update_heartbeat()

        except Exception as e:
            logger.exception("Failed to display image: %s / %s", image_path, e)

        NEXT_IMAGE_EVENT.clear()
        NEXT_IMAGE_EVENT.wait(CONFIG["INTERVAL_SECONDS"])


if __name__ == "__main__":
    main()
