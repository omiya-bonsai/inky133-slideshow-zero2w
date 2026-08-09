#!/usr/bin/python3
"""
Pimoroni Inky Impression 13.3" Spectra 6 / 1600x1200
v1.1 preprocessing pipeline 対応スライドショー

設計:
- Mac側で完成済みの P-mode PNG を表示する
- photo / illustration の判定や画像補正はPi側では行わない
- 撮影日は photos/metadata.json から取得
- 画像はランダム順
- Mac側で作った6色/モノクロのP-modeを維持
- Pi側では日付・更新時刻・uptimeだけをオーバーレイ
"""

import json
import logging
import os
import random
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from dotenv import load_dotenv


load_dotenv()


# ============================================================
# Paths / state
# ============================================================

SCRIPT_DIR = Path(__file__).resolve().parent

IMAGE_DIR = Path(
    os.getenv(
        "PHOTO_DIR",
        str(SCRIPT_DIR / "photos" / "auto"),
    )
)

METADATA_FILE = Path(
    os.getenv(
        "METADATA_FILE",
        str(SCRIPT_DIR / "photos" / "metadata.json"),
    )
)

STATE_FILE = Path.home() / ".cache" / "slideshow_state_133.json"
COUNTER_FILE = Path.home() / ".logs" / "slideshow_counter_133.txt"
HEARTBEAT_PATH = Path("/tmp/inky_slideshow_heartbeat")


# ============================================================
# Runtime state
# ============================================================

NEXT_IMAGE_EVENT = threading.Event()
BUTTON_B_PRESSED_AT = None


# ============================================================
# Configuration
# ============================================================

CONFIG = {
    "FONT_PATH": os.getenv(
        "FONT_PATH",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),

    "INTERVAL_SECONDS": int(
        os.getenv("INTERVAL_SECONDS", "1800")
    ),

    "FONT_SIZE": 20,
    "DATE_FONT_SIZE": 24,

    "DATE_POSITIONS": [
        "bottom-right",
        "top-right",
        "top-left",
        "bottom-left",
    ],

    "MARGIN": 25,
    "BACKGROUND_PADDING": 15,
    "TEXT_PADDING": 12,
    "LINE_SPACING": 8,
}


logger = None


# ============================================================
# Logging
# ============================================================

def setup_logging():
    log_dir = Path.home() / ".logs" / "slideshow_logs"
    log_dir.mkdir(parents=True, exist_ok=True)

    log_file = log_dir / "slideshow_133.log"

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(log_file),
            logging.StreamHandler(),
        ],
    )

    return logging.getLogger(__name__)


# ============================================================
# Inky
# ============================================================

def initialize_display():
    """
    13.3" Spectra 6 を自動検出する。

    Dummy displayへ黙ってフォールバックしない。
    ハードウェア初期化に失敗した場合は、その場で異常終了させる。
    """
    from inky.auto import auto

    inky = auto(verbose=True)

    logger.info(
        "Detected display: %s / %dx%d",
        type(inky).__name__,
        inky.width,
        inky.height,
    )

    if (inky.width, inky.height) != (1600, 1200):
        raise RuntimeError(
            f"Unexpected display resolution: "
            f"{inky.width}x{inky.height}"
        )

    if hasattr(inky, "set_border"):
        inky.set_border(inky.WHITE)

    return inky


# ============================================================
# Buttons
# ============================================================

def setup_buttons():
    global BUTTON_B_PRESSED_AT

    try:
        from gpiozero import Button
    except Exception as exc:
        logger.warning(
            "gpiozero not available, buttons disabled: %s",
            exc,
        )
        return []

    btn_a = Button(
        5,
        pull_up=True,
        bounce_time=0.08,
    )

    btn_b = Button(
        6,
        pull_up=True,
        bounce_time=0.08,
    )

    def on_a_pressed():
        logger.info(
            "Button A pressed: next image requested"
        )
        NEXT_IMAGE_EVENT.set()

    def on_b_pressed():
        global BUTTON_B_PRESSED_AT

        BUTTON_B_PRESSED_AT = time.monotonic()

        logger.info("Button B pressed")

    def on_b_released():
        global BUTTON_B_PRESSED_AT

        if BUTTON_B_PRESSED_AT is None:
            return

        held = (
            time.monotonic()
            - BUTTON_B_PRESSED_AT
        )

        BUTTON_B_PRESSED_AT = None

        if held >= 3.0:
            logger.warning(
                "Button B long press %.2fs: poweroff",
                held,
            )

            subprocess.Popen(
                ["sudo", "/usr/sbin/poweroff"]
            )

        else:
            logger.warning(
                "Button B short press %.2fs: reboot",
                held,
            )

            subprocess.Popen(
                ["sudo", "/usr/sbin/reboot"]
            )

    btn_a.when_pressed = on_a_pressed
    btn_b.when_pressed = on_b_pressed
    btn_b.when_released = on_b_released

    logger.info(
        "Buttons enabled: "
        "A=next, B=reboot, long-B=poweroff"
    )

    return [btn_a, btn_b]


# ============================================================
# Metadata
# ============================================================

def load_metadata():
    if not METADATA_FILE.exists():
        logger.warning(
            "Metadata file not found: %s",
            METADATA_FILE,
        )
        return {}

    try:
        with METADATA_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            data = json.load(f)

        logger.info(
            "Metadata loaded: %d entries",
            len(data),
        )

        return data

    except Exception:
        logger.exception(
            "Failed to load metadata: %s",
            METADATA_FILE,
        )
        return {}


def parse_capture_date(value):
    """
    Mac側metadataに保存される各種日時表記を受け入れる。

    例:
      2019:04:10 12:48:04
      2019-04-10 12:48:04
      2019-04-10T12:48:04
    """
    if not value:
        return None

    value = str(value).strip()

    # ExifToolのtimezone付きFileModifyDateへの保険
    if len(value) >= 19:
        candidate = value[:19]
    else:
        candidate = value

    formats = (
        "%Y:%m:%d %H:%M:%S",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M:%S",
    )

    for fmt in formats:
        try:
            return datetime.strptime(
                candidate,
                fmt,
            )
        except ValueError:
            pass

    return None


def get_metadata_entry(image_path, metadata):
    """
    v1.1では基本的にoutput filenameがmetadata key。

    将来metadata構造を少し変えても動くよう、
    source/output関連キーもフォールバック検索する。
    """
    filename = Path(image_path).name

    if filename in metadata:
        return metadata[filename]

    for key, entry in metadata.items():
        if not isinstance(entry, dict):
            continue

        possible_names = {
            Path(str(key)).name,
        }

        for field in (
            "output",
            "output_name",
            "filename",
        ):
            value = entry.get(field)

            if value:
                possible_names.add(
                    Path(str(value)).name
                )

        if filename in possible_names:
            return entry

    return None


def get_capture_date(
    image_path,
    metadata,
):
    entry = get_metadata_entry(
        image_path,
        metadata,
    )

    if not entry:
        logger.warning(
            "Metadata entry not found: %s",
            Path(image_path).name,
        )
        return None

    return parse_capture_date(
        entry.get("capture_date")
    )


def get_display_mode(
    image_path,
    metadata,
):
    """
    ログ表示用。

    画像表示処理そのものには使わない。
    """
    entry = get_metadata_entry(
        image_path,
        metadata,
    )

    if not entry:
        return "unknown"

    return (
        entry.get("display_mode")
        or entry.get("mode")
        or entry.get(
            "classification",
            {},
        ).get("display_mode")
        or "unknown"
    )


# ============================================================
# State
# ============================================================

def save_state(queue, total_count):
    try:
        STATE_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with STATE_FILE.open(
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(
                {
                    "total_count": total_count,
                    "queue": queue,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )

    except Exception:
        logger.exception(
            "Failed to save state"
        )


def load_state():
    try:
        with STATE_FILE.open(
            "r",
            encoding="utf-8",
        ) as f:
            state = json.load(f)

        return (
            state.get("total_count", 0),
            state.get("queue", []),
        )

    except Exception:
        return 0, []


def reset_state():
    try:
        STATE_FILE.unlink(missing_ok=True)
    except Exception:
        pass


# ============================================================
# Display counter
# ============================================================

def load_display_counter():
    try:
        return int(
            COUNTER_FILE.read_text().strip()
        )
    except Exception:
        return 0


def save_display_counter(counter):
    try:
        COUNTER_FILE.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        COUNTER_FILE.write_text(
            str(counter)
        )

    except Exception:
        logger.exception(
            "Failed to save display counter"
        )


# ============================================================
# Heartbeat
# ============================================================

def update_heartbeat():
    try:
        HEARTBEAT_PATH.write_text(
            datetime.now().isoformat(
                timespec="minutes"
            )
        )

    except Exception:
        logger.exception(
            "Failed to update heartbeat"
        )


# ============================================================
# uptime
# ============================================================

def get_system_uptime_seconds():
    try:
        with open(
            "/proc/uptime",
            "r",
            encoding="utf-8",
        ) as f:
            first = f.read().split()[0]

        return max(
            0,
            int(float(first)),
        )

    except Exception:
        return 0


def format_uptime_htop(uptime_seconds):
    uptime_seconds = max(
        0,
        int(uptime_seconds),
    )

    days, rem = divmod(
        uptime_seconds,
        86400,
    )

    hh, rem = divmod(
        rem,
        3600,
    )

    mm, ss = divmod(
        rem,
        60,
    )

    if days > 0:
        return (
            f"{days} "
            f"{'day' if days == 1 else 'days'}, "
            f"{hh:02d}:{mm:02d}:{ss:02d}"
        )

    return (
        f"{hh:02d}:"
        f"{mm:02d}:"
        f"{ss:02d}"
    )


# ============================================================
# Image collection
# ============================================================

def collect_images():
    if not IMAGE_DIR.exists():
        return []

    images = []

    for path in IMAGE_DIR.rglob("*.png"):
        if not path.is_file():
            continue

        if path.name.startswith("."):
            continue

        images.append(
            str(path.resolve())
        )

    return sorted(images)


def reconcile_queue(
    queue,
    current_images,
):
    """
    古いphotos/パスがstateに残っていても安全に捨てる。

    入力画像が増減した場合は、新しいシャッフルキューを作る。
    """
    current_set = set(current_images)

    valid_queue = [
        path
        for path in queue
        if path in current_set
        and os.path.exists(path)
    ]

    if (
        len(current_images)
        != len(valid_queue)
        and not valid_queue
    ):
        return []

    return valid_queue


# ============================================================
# Date text
# ============================================================

def format_date_and_elapsed_time(
    capture_date,
):
    if not capture_date:
        return (
            "Unknown date",
            "Unknown date",
            "Unknown date",
        )

    now = datetime.now()

    formatted_date = (
        capture_date.strftime(
            "%Y-%m-%d"
        )
    )

    days = (
        now - capture_date
    ).days

    if days >= 365:
        years = days // 365
        elapsed_text = (
            f"{years} "
            f"{'year' if years == 1 else 'years'} "
            f"ago"
        )

    elif days >= 30:
        months = days // 30
        elapsed_text = (
            f"{months} "
            f"{'month' if months == 1 else 'months'} "
            f"ago"
        )

    else:
        elapsed_text = (
            "Within a month"
        )

    if days >= 0:
        days_ago_text = (
            f"{days} days ago "
            f"(from today)"
        )

    else:
        days_ago_text = (
            f"{abs(days)} days "
            f"from today"
        )

    return (
        formatted_date,
        elapsed_text,
        days_ago_text,
    )


# ============================================================
# Fonts
# ============================================================

def load_font(size):
    try:
        return ImageFont.truetype(
            CONFIG["FONT_PATH"],
            size,
        )
    except OSError:
        logger.warning(
            "Font unavailable: %s",
            CONFIG["FONT_PATH"],
        )

        return ImageFont.load_default()


# ============================================================
# Overlays
# ============================================================

def add_date_overlay(
    img,
    capture_date,
):
    """
    P-modeのまま描画する。

    Inky palette:
      index 0 = BLACK
      index 1 = WHITE

    RGBへ変換しないことが重要。
    """
    if img.mode != "P":
        raise ValueError(
            f"Expected P-mode image, got {img.mode}"
        )

    draw = ImageDraw.Draw(img)

    font_small = load_font(
        CONFIG["FONT_SIZE"]
    )

    font_large = load_font(
        CONFIG["DATE_FONT_SIZE"]
    )

    (
        date_text,
        elapsed_text,
        days_ago_text,
    ) = format_date_and_elapsed_time(
        capture_date
    )

    position = random.choice(
        CONFIG["DATE_POSITIONS"]
    )

    margin = CONFIG["MARGIN"]
    padding = CONFIG[
        "BACKGROUND_PADDING"
    ]

    bbox1 = draw.textbbox(
        (0, 0),
        date_text,
        font=font_large,
    )

    bbox2 = draw.textbbox(
        (0, 0),
        elapsed_text,
        font=font_small,
    )

    bbox3 = draw.textbbox(
        (0, 0),
        days_ago_text,
        font=font_small,
    )

    width = max(
        bbox1[2] - bbox1[0],
        bbox2[2] - bbox2[0],
        bbox3[2] - bbox3[0],
    )

    h1 = bbox1[3] - bbox1[1]
    h2 = bbox2[3] - bbox2[1]
    h3 = bbox3[3] - bbox3[1]

    height = (
        h1
        + h2
        + h3
        + CONFIG["TEXT_PADDING"] * 2
    )

    if "right" in position:
        x = (
            img.width
            - width
            - margin
            - padding
        )
    else:
        x = margin + padding

    if "bottom" in position:
        y = (
            img.height
            - height
            - margin
            - padding
        )
    else:
        y = margin + padding

    # 1 = white
    draw.rectangle(
        (
            x - padding,
            y - padding,
            x + width + padding,
            y + height + padding,
        ),
        fill=1,
    )

    # 0 = black
    draw.text(
        (x, y),
        date_text,
        fill=0,
        font=font_large,
    )

    y2 = (
        y
        + h1
        + CONFIG["TEXT_PADDING"]
    )

    draw.text(
        (x, y2),
        elapsed_text,
        fill=0,
        font=font_small,
    )

    y3 = (
        y2
        + h2
        + CONFIG["TEXT_PADDING"]
    )

    draw.text(
        (x, y3),
        days_ago_text,
        fill=0,
        font=font_small,
    )

    return img, position


def add_status_overlay(
    img,
    date_position,
    slide_updated_at,
):
    if img.mode != "P":
        raise ValueError(
            f"Expected P-mode image, got {img.mode}"
        )

    draw = ImageDraw.Draw(img)

    font = load_font(
        CONFIG["FONT_SIZE"]
    )

    updated_str = (
        "Updated: "
        f"{slide_updated_at.strftime('%Y-%m-%d %H:%M')}"
    )

    uptime_str = (
        "Uptime: "
        f"{format_uptime_htop(get_system_uptime_seconds())}"
    )

    text_block = (
        f"{updated_str}\n"
        f"{uptime_str}"
    )

    opposite = {
        "bottom-right": "top-left",
        "top-right": "bottom-left",
        "top-left": "bottom-right",
        "bottom-left": "top-right",
    }.get(
        date_position,
        "bottom-left",
    )

    margin = CONFIG["MARGIN"]
    padding = CONFIG[
        "BACKGROUND_PADDING"
    ]

    bbox = draw.multiline_textbbox(
        (0, 0),
        text_block,
        font=font,
        spacing=CONFIG[
            "LINE_SPACING"
        ],
    )

    width = (
        bbox[2] - bbox[0]
    )

    height = (
        bbox[3] - bbox[1]
    )

    if "right" in opposite:
        x = (
            img.width
            - width
            - margin
            - padding
        )
    else:
        x = (
            margin
            + padding
        )

    if "bottom" in opposite:
        y = (
            img.height
            - height
            - margin
            - padding
        )
    else:
        y = (
            margin
            + padding
        )

    draw.rectangle(
        (
            x - padding,
            y - padding,
            x + width + padding,
            y + height + padding,
        ),
        fill=1,
    )

    draw.multiline_text(
        (x, y),
        text_block,
        fill=0,
        font=font,
        spacing=CONFIG[
            "LINE_SPACING"
        ],
    )

    return img


# ============================================================
# Prepare final display image
# ============================================================

def prepare_image(
    image_path,
    inky_display,
    slide_updated_at,
    metadata,
):
    with Image.open(image_path) as source:
        if source.mode != "P":
            raise ValueError(
                f"Generated image must be P-mode: "
                f"{image_path} / mode={source.mode}"
            )

        if source.size != (
            inky_display.width,
            inky_display.height,
        ):
            raise ValueError(
                f"Unexpected image size: "
                f"{image_path} / "
                f"{source.size}"
            )

        # load()してからcopy()することで
        # withブロック外でも安全な独立画像にする。
        source.load()
        img = source.copy()

    if img.palette is None:
        raise ValueError(
            f"Missing palette: {image_path}"
        )

    capture_date = get_capture_date(
        image_path,
        metadata,
    )

    img, date_position = add_date_overlay(
        img,
        capture_date,
    )

    img = add_status_overlay(
        img,
        date_position,
        slide_updated_at,
    )

    return img


# ============================================================
# Main
# ============================================================

def main():
    global logger

    logger = setup_logging()

    logger.info(
        "=== Inky 13.3 slideshow starting ==="
    )

    logger.info(
        "Image directory: %s",
        IMAGE_DIR,
    )

    logger.info(
        "Metadata file: %s",
        METADATA_FILE,
    )

    metadata = load_metadata()

    inky = initialize_display()
    buttons = setup_buttons()

    # buttonsをローカル変数として保持し、
    # gpiozero ButtonがGCされないようにする。
    _buttons = buttons

    counter = load_display_counter()

    saved_count, queue = load_state()

    current_images = collect_images()

    if not current_images:
        raise RuntimeError(
            f"No PNG images found: {IMAGE_DIR}"
        )

    if saved_count != len(
        current_images
    ):
        logger.info(
            "Image count changed: "
            "%d -> %d; resetting queue",
            saved_count,
            len(current_images),
        )
        queue = []

    else:
        queue = reconcile_queue(
            queue,
            current_images,
        )

    while True:
        if not queue:
            current_images = collect_images()

            if not current_images:
                logger.error(
                    "No PNG images found: %s",
                    IMAGE_DIR,
                )

                time.sleep(60)
                continue

            queue = current_images.copy()

            random.shuffle(queue)

            logger.info(
                "Image queue created: %d images",
                len(queue),
            )

        image_path = queue.pop(0)

        if not os.path.exists(
            image_path
        ):
            logger.warning(
                "Missing image skipped: %s",
                image_path,
            )

            save_state(
                queue,
                len(current_images),
            )

            continue

        counter += 1

        slide_updated_at = (
            datetime.now()
        )

        try:
            mode = get_display_mode(
                image_path,
                metadata,
            )

            logger.info(
                "Displaying #%d: %s / mode=%s",
                counter,
                image_path,
                mode,
            )

            img = prepare_image(
                image_path,
                inky,
                slide_updated_at,
                metadata,
            )

            logger.info(
                "Prepared: mode=%s / size=%s / "
                "palette_colours=%d",
                img.mode,
                img.size,
                len(img.palette.colors)
                if img.palette
                else 0,
            )

            # ここでRGBへ変換しない。
            # Macで生成したP-mode PNGをそのまま渡す。
            inky.set_image(img)
            inky.show()

            save_display_counter(
                counter
            )

            save_state(
                queue,
                len(current_images),
            )

            update_heartbeat()

            logger.info(
                "Display completed: #%d",
                counter,
            )

        except Exception:
            logger.exception(
                "Failed to display image: %s",
                image_path,
            )

        NEXT_IMAGE_EVENT.clear()

        NEXT_IMAGE_EVENT.wait(
            CONFIG[
                "INTERVAL_SECONDS"
            ]
        )


if __name__ == "__main__":
    main()
