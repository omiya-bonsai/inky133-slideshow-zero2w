#!/usr/bin/python3
"""
Pimoroni Inky Impression 13.3" (2025 Edition / 1600x1200) 用 スライドショープログラム
- 2025年版 Inky ライブラリの複数クラスに対応
- スライド表示状態の保存（キュー / 全枚数）
- get_throttled 監視とは別に、表示カウンタ & ハートビートファイルを更新
- 画像ごとに撮影日 + 経過年月 + きょうから何日前を四隅のどこかにオーバーレイ
- 日付オーバーレイの対角線上に
  「スライド更新日時（秒なし）」と
  「起動からの経過時間（day対応・秒なし）」を表示
"""

# ===== 標準ライブラリ =====
import os
import time
import random
import logging
import json
from datetime import datetime

# ===== サードパーティ =====
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import piexif
from dotenv import load_dotenv

# .env ファイル読み込み
load_dotenv()

# ==================== 定数・設定 ====================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.expanduser("~/.cache/slideshow_state_133.json")
COUNTER_FILE = os.path.expanduser("~/.logs/slideshow_counter_133.txt")
HEARTBEAT_PATH = "/tmp/inky_slideshow_heartbeat"

CONFIG = {
    "PHOTO_DIR": os.path.join(SCRIPT_DIR, os.getenv("PHOTO_DIR", "photos")),
    "FONT_PATH": os.getenv(
        "FONT_PATH",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ),
    "INTERVAL_SECONDS": int(os.getenv("INTERVAL_SECONDS", 1800)),
    "FONT_SIZE": 20,
    "DATE_FONT_SIZE": 24,
    "DATE_POSITIONS": ['bottom-right', 'top-right', 'top-left', 'bottom-left'],
    "MARGIN": 25,
    "BACKGROUND_PADDING": 15,
    "TEXT_PADDING": 12,
    "CONTRAST": 1.1,
}

logger = None


# ==================== ログ初期化 ====================

def setup_logging():
    log_dir = os.path.expanduser("~/.logs/slideshow_logs")
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(log_dir, "slideshow_133.log")
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler()
        ]
    )
    return logging.getLogger(__name__)


# ==================== Inky 初期化 ====================

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


# ==================== 状態・カウンタ ====================

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


# ==================== 画像処理 ====================

def extract_capture_date(image_path):
    if image_path.lower().endswith(".png"):
        return None
    try:
        exif_dict = piexif.load(image_path)
        date_str = exif_dict["Exif"].get(piexif.ExifIFD.DateTimeOriginal)
        if date_str:
            return datetime.strptime(date_str.decode("utf-8"), "%Y:%m:%d %H:%M:%S")
    except Exception:
        pass
    return None


def format_date_and_elapsed_time(capture_date):
    if not capture_date:
        return "Unknown date", "Unknown date", "Unknown date"

    now = datetime.now()
    formatted_date = capture_date.strftime("%Y-%m-%d")
    days = (now - capture_date).days

    # 何年前（概算）
    if days >= 365:
        elapsed_text = f"{days // 365} years ago"
    elif days >= 30:
        elapsed_text = f"{days // 30} months ago"
    else:
        elapsed_text = "Within a month"

    # きょうから何日前（厳密）
    if days >= 0:
        days_ago_text = f"{days} days ago (from today)"
    else:
        days_ago_text = f"{abs(days)} days from today"

    return formatted_date, elapsed_text, days_ago_text


def enhance_image(img):
    return ImageEnhance.Contrast(img).enhance(CONFIG["CONTRAST"])


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

    width = max(bbox1[2], bbox2[2], bbox3[2])

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


def add_status_overlay(img, date_position, slide_updated_at, program_started_at):
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype(CONFIG["FONT_PATH"], CONFIG["FONT_SIZE"])
    except OSError:
        font = ImageFont.load_default()

    updated_str = f"Updated: {slide_updated_at.strftime('%Y-%m-%d %H:%M')}"

    uptime_seconds = int((slide_updated_at - program_started_at).total_seconds())
    days = uptime_seconds // 86400
    rem = uptime_seconds % 86400
    hh = rem // 3600
    mm = (rem % 3600) // 60

    uptime_str = f"Uptime: {days}d {hh:02d}:{mm:02d}"

    lines = [updated_str, uptime_str]

    opposite = {
        "bottom-right": "top-left",
        "top-right": "bottom-left",
        "top-left": "bottom-right",
        "bottom-left": "top-right",
    }.get(date_position, "bottom-left")

    margin = CONFIG["MARGIN"]
    padding = CONFIG["BACKGROUND_PADDING"]

    bboxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    width = max(b[2] - b[0] for b in bboxes)
    height = sum((b[3] - b[1]) for b in bboxes) + CONFIG["TEXT_PADDING"]

    x = img.width - width - margin - padding if "right" in opposite else margin + padding
    y = img.height - height - margin - padding if "bottom" in opposite else margin + padding

    draw.rectangle(
        (x - padding, y - padding, x + width + padding, y + height + padding),
        fill="white",
    )

    yy = y
    for line, bbox in zip(lines, bboxes):
        draw.text((x, yy), line, fill="black", font=font)
        yy += (bbox[3] - bbox[1]) + CONFIG["TEXT_PADDING"]

    return img


def prepare_image(image_path, inky_display, slide_updated_at, program_started_at, counter):
    with Image.open(image_path) as img:
        img = enhance_image(img.convert("RGB"))
        img = img.resize((inky_display.width, inky_display.height), Image.Resampling.LANCZOS)
        img, pos = add_date_overlay(img, extract_capture_date(image_path))
        img = add_status_overlay(img, pos, slide_updated_at, program_started_at)
        return img


# ==================== メイン ====================

def main():
    program_started_at = datetime.now()
    inky = initialize_display()
    global logger
    logger = setup_logging()

    counter = load_display_counter()
    _, queue = load_state()

    while True:
        if not queue:
            queue = [
                os.path.join(CONFIG["PHOTO_DIR"], f)
                for f in os.listdir(CONFIG["PHOTO_DIR"])
                if f.lower().endswith((".jpg", ".jpeg", ".png"))
            ]
            random.shuffle(queue)

        image_path = queue.pop(0)
        counter += 1
        slide_updated_at = datetime.now()

        img = prepare_image(image_path, inky, slide_updated_at, program_started_at, counter)
        inky.set_image(img)
        inky.show()

        save_display_counter(counter)
        save_state(queue, len(queue))
        update_heartbeat()
        time.sleep(CONFIG["INTERVAL_SECONDS"])


if __name__ == "__main__":
    main()
