#!/usr/bin/python3
"""
Pimoroni Inky Impression 13.3" (2025 Edition / 1600x1200) 用 スライドショープログラム
- 2025年版 Inky ライブラリの複数クラスに対応
- スライド表示状態の保存（キュー / 全枚数）
- get_throttled 監視とは別に、表示カウンタ & ハートビートファイルを更新
- 画像ごとに撮影日 + 経過年月を四隅のどこかにオーバーレイ
- 表示カウンタもパネル上に表示
"""

# ===== 標準ライブラリ =====
import os
import time
import random
import logging
import json
import traceback
from datetime import datetime

# ===== サードパーティ =====
from PIL import Image, ImageDraw, ImageFont, ImageEnhance
import piexif
from dotenv import load_dotenv

# .env ファイル読み込み
load_dotenv()

# ==================== 定数・設定 ====================

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.expanduser("~/.cache/slideshow_state_133.json")  # 画像キューの状態保存
COUNTER_FILE = os.path.expanduser("~/.logs/slideshow_counter_133.txt")  # 表示カウンタ保存
HEARTBEAT_PATH = "/tmp/inky_slideshow_heartbeat"  # watchdog 用ハートビート

CONFIG = {
    # --- .env から読む設定 ---
    "PHOTO_DIR": os.path.join(SCRIPT_DIR, os.getenv("PHOTO_DIR", "photos")),
    "FONT_PATH": os.getenv(
        "FONT_PATH",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
    ),
    "INTERVAL_SECONDS": int(os.getenv("INTERVAL_SECONDS", 1800)),

    # --- 固定設定 ---
    "FONT_SIZE": 20,
    "DATE_FONT_SIZE": 24,
    "COUNTER_FONT_SIZE": 20,
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
    """
    ディスプレイの初期化を試行し、複数のクラス名に対応
    """
    possible_classes = [
        ("inky", "Inky"),                           # 汎用クラス
        ("inky.inky_impression", "InkyImpression"), # Impression シリーズ
        ("inky.inky_el133uf1", "InkyEL133UF1"),     # 13.3" 従来版
        ("inky.inky_impression", "InkyImpression133"),  # 13.3" 新版
        ("inky.auto", "auto"),                      # 自動検出
    ]

    for module_name, class_name in possible_classes:
        try:
            print(f"試行中: {module_name}.{class_name}")

            if class_name == "auto":
                from inky.auto import auto
                inky_display = auto()
            else:
                module = __import__(module_name, fromlist=[class_name])
                InkyClass = getattr(module, class_name)
                try:
                    inky_display = InkyClass(resolution=(1600, 1200))
                    print(f"解像度指定での初期化に成功: {class_name}")
                except TypeError:
                    inky_display = InkyClass()
                    print(f"標準初期化に成功: {class_name}")

            print(f"✅ ディスプレイ初期化成功: {inky_display.width}x{inky_display.height}")

            try:
                if hasattr(inky_display, "set_border"):
                    inky_display.set_border(inky_display.WHITE)
                    print("境界線の設定が完了しました")
            except Exception as e:
                print(f"境界線設定の警告: {e}")

            return inky_display

        except ImportError:
            print(f"❌ {module_name}.{class_name}: インポートエラー")
        except AttributeError:
            print(f"❌ {module_name}.{class_name}: 属性エラー")
        except IndexError:
            print(f"❌ {module_name}.{class_name}: 範囲外エラー (display_variant 問題)")
        except Exception as e:
            print(f"❌ {module_name}.{class_name}: その他のエラー - {e}")

    print("\n=== 代替初期化方法を試行 ===")
    return try_alternative_initialization()


def try_alternative_initialization():
    """
    EEPROM の display_variant 問題を回避した代替初期化
    """
    try:
        from inky.eeprom import read_eeprom
        eeprom_data = read_eeprom()
        if eeprom_data and hasattr(eeprom_data, "display_variant"):
            print(f"EEPROM display_variant: {eeprom_data.display_variant}")
            if eeprom_data.display_variant > 2:
                print("display_variant を 0 に修正して再試行...")
                eeprom_data.display_variant = 0

        from inky.inky_impression import InkyImpression
        inky_display = InkyImpression(
            colour="7colour",
            resolution=(1600, 1200)
        )
        print("✅ 代替方法での初期化に成功しました")
        return inky_display

    except Exception as e:
        print(f"❌ 代替方法も失敗: {e}")
        print("⚠️  ダミーディスプレイクラスを作成します（テスト用）")
        return create_dummy_display()


def create_dummy_display():
    class DummyDisplay:
        def __init__(self):
            self.width = 1600
            self.height = 1200
            self.WHITE = (255, 255, 255)

        def set_border(self, color):
            print(f"ダミー: 境界線を {color} に設定")

        def set_image(self, image):
            print(f"ダミー: 画像を設定 ({image.size})")

        def show(self):
            print("ダミー: 画像を表示（実際の表示はされません）")

    return DummyDisplay()


# ==================== 状態・カウンタ・ハートビート ====================

def save_state(queue, total_count):
    state = {"total_count": total_count, "queue": queue}
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as f:
            json.dump(state, f)
        if logger:
            logger.info(f"現在の状態を保存しました。残り: {len(queue)} / {total_count}枚")
    except Exception as e:
        if logger:
            logger.error(f"状態の保存に失敗しました: {e}")


def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, "r") as f:
                state = json.load(f)
            if isinstance(state, dict):
                count = state.get("total_count", 0)
                queue = state.get("queue", [])
                if logger:
                    logger.info(f"前回の状態を読み込みました。残り: {len(queue)} / {count}枚")
                return count, queue
            elif isinstance(state, list):
                if logger:
                    logger.info("古い状態ファイルを検出しました。リセットします。")
                return 0, state
        except Exception as e:
            if logger:
                logger.error(f"状態の読み込みに失敗しました: {e}")
    return 0, []


def load_display_counter():
    """
    表示カウンタをファイルから読み出し
    """
    try:
        if os.path.exists(COUNTER_FILE):
            with open(COUNTER_FILE, "r", encoding="utf-8") as f:
                value = int(f.read().strip() or "0")
                return value
    except Exception:
        pass
    return 0


def save_display_counter(counter: int):
    """
    表示カウンタをファイルへ保存
    """
    try:
        os.makedirs(os.path.dirname(COUNTER_FILE), exist_ok=True)
        with open(COUNTER_FILE, "w", encoding="utf-8") as f:
            f.write(str(counter))
    except Exception as e:
        if logger:
            logger.error(f"表示カウンタの保存に失敗しました: {e}")


def update_heartbeat():
    """
    watchdog 用ハートビートファイルを更新
    """
    try:
        with open(HEARTBEAT_PATH, "w", encoding="utf-8") as f:
            f.write(datetime.now().isoformat(timespec="seconds"))
    except Exception as e:
        if logger:
            logger.error(f"ハートビートファイルの更新に失敗しました: {e}")


# ==================== 画像まわり ====================

def extract_capture_date(image_path):
    if image_path.lower().endswith(".png"):
        return None
    try:
        exif_dict = piexif.load(image_path)
        date_str = exif_dict["Exif"].get(piexif.ExifIFD.DateTimeOriginal)
        if date_str:
            return datetime.strptime(date_str.decode("utf-8"), "%Y:%m:%d %H:%M:%S")
        return None
    except Exception:
        return None


def format_date_and_elapsed_time(capture_date):
    if not capture_date:
        return "Unknown date", "Unknown date"
    formatted_date = capture_date.strftime("%Y-%m-%d")
    days = (datetime.now() - capture_date).days
    years = days // 365
    if years > 0:
        elapsed = f"{years} year{'s' if years > 1 else ''} ago"
    else:
        months = days // 30
        elapsed = (
            f"{months} month{'s' if months > 1 else ''} ago"
            if months > 0
            else "Within a month"
        )
    return formatted_date, elapsed


def enhance_image(img):
    return ImageEnhance.Contrast(img).enhance(CONFIG["CONTRAST"])


def add_date_overlay(img, capture_date):
    draw = ImageDraw.Draw(img)
    try:
        elapsed_font = ImageFont.truetype(CONFIG["FONT_PATH"], CONFIG["FONT_SIZE"])
        date_font = ImageFont.truetype(CONFIG["FONT_PATH"], CONFIG["DATE_FONT_SIZE"])
    except OSError:
        if logger:
            logger.warning("指定フォントが見つかりません。デフォルトフォントを使用します。")
        elapsed_font = date_font = ImageFont.load_default()

    formatted_date, elapsed_time = format_date_and_elapsed_time(capture_date)
    date_bbox = draw.textbbox((0, 0), formatted_date, font=date_font)
    elapsed_bbox = draw.textbbox((0, 0), elapsed_time, font=elapsed_font)

    max_width = max(date_bbox[2], elapsed_bbox[2])
    total_height = (
        (date_bbox[3] - date_bbox[1])
        + (elapsed_bbox[3] - elapsed_bbox[1])
        + CONFIG["TEXT_PADDING"]
    )

    margin = CONFIG["MARGIN"]
    padding = CONFIG["BACKGROUND_PADDING"]

    position = random.choice(CONFIG["DATE_POSITIONS"])
    x = (
        img.width - max_width - margin - padding
        if "right" in position
        else margin + padding
    )
    y = (
        img.height - total_height - margin - padding
        if "bottom" in position
        else margin + padding
    )

    draw.rectangle(
        (x - padding, y - padding, x + max_width + padding, y + total_height + padding),
        fill="white",
    )
    draw.text((x, y), formatted_date, fill="black", font=date_font)
    draw.text(
        (x, y + (date_bbox[3] - date_bbox[1]) + CONFIG["TEXT_PADDING"]),
        elapsed_time,
        fill="black",
        font=elapsed_font,
    )
    return img


def add_counter_overlay(img, counter: int):
    """
    パネル上に表示カウンタをオーバーレイする
    （左下固定でシンプルに表示）
    """
    draw = ImageDraw.Draw(img)
    try:
        counter_font = ImageFont.truetype(
            CONFIG["FONT_PATH"], CONFIG["COUNTER_FONT_SIZE"]
        )
    except OSError:
        counter_font = ImageFont.load_default()

    text = f"#{counter}"
    bbox = draw.textbbox((0, 0), text, font=counter_font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]

    margin = CONFIG["MARGIN"]
    padding = CONFIG["BACKGROUND_PADDING"]

    x = margin + padding
    y = img.height - text_height - margin - padding

    draw.rectangle(
        (x - padding, y - padding, x + text_width + padding, y + text_height + padding),
        fill="white",
    )
    draw.text((x, y), text, fill="black", font=counter_font)

    return img


def prepare_image(image_path, inky_display, display_counter: int):
    try:
        if logger:
            logger.info(f"画像処理開始: {os.path.basename(image_path)} (counter={display_counter})")

        with Image.open(image_path) as original_img:
            target_width, target_height = inky_display.width, inky_display.height

            rgb_img = original_img.convert("RGB")
            enhanced_img = enhance_image(rgb_img)

            img_ratio = enhanced_img.width / enhanced_img.height
            target_ratio = target_width / target_height

            if img_ratio > target_ratio:
                new_height = target_height
                new_width = int(target_height * img_ratio)
            else:
                new_width = target_width
                new_height = int(target_width / img_ratio)

            resized_img = enhanced_img.resize(
                (new_width, new_height),
                resample=Image.Resampling.LANCZOS,
            )

            left = (new_width - target_width) // 2
            top = (new_height - target_height) // 2
            cropped_img = resized_img.crop(
                (left, top, left + target_width, top + target_height)
            )

            capture_date = extract_capture_date(image_path)
            with_date = add_date_overlay(cropped_img, capture_date)

            with_counter = add_counter_overlay(with_date, display_counter)

            return with_counter

    except Exception as e:
        if logger:
            logger.error(
                f"画像処理エラー [{os.path.basename(image_path)}]: {str(e)}\n{traceback.format_exc()}"
            )
        return None


# ==================== メイン処理 ====================

def main():
    global logger

    print('=== Inky Impression 13.3" スライドショー（2025年版対応）を起動します ===')

    inky_display = initialize_display()
    if inky_display is None:
        print("\nディスプレイの初期化に失敗したため、プログラムを終了します。")
        return

    logger = setup_logging()
    logger.info("ロギングシステムの初期化が完了しました。")
    logger.info(
        f"Display class: {inky_display.__class__.__module__}.{inky_display.__class__.__name__}, "
        f"resolution: {inky_display.width}x{inky_display.height}"
    )

    photo_dir = CONFIG["PHOTO_DIR"]
    if not os.path.isdir(photo_dir):
        logger.error(f"画像ディレクトリが見つかりません: {photo_dir}")
        return

    current_files = [
        os.path.join(photo_dir, f)
        for f in os.listdir(photo_dir)
        if f.lower().endswith((".jpg", ".jpeg", ".png"))
    ]
    current_file_count = len(current_files)

    saved_count, display_queue = load_state()
    if current_file_count != saved_count:
        logger.info(
            f"画像数の変動を検知 (前回:{saved_count} -> 現在:{current_file_count})。キューをリセットします。"
        )
        display_queue = []

    total_in_cycle = current_file_count

    # 表示カウンタの読み込み
    display_counter = load_display_counter()
    logger.info(f"表示カウンタ初期値: {display_counter}")

    # 初回ハートビート更新
    update_heartbeat()

    while True:
        try:
            if not display_queue:
                logger.info("表示キューが空です。全画像リストを再生成します。")
                all_files = [
                    os.path.join(photo_dir, f)
                    for f in os.listdir(photo_dir)
                    if f.lower().endswith((".jpg", ".jpeg", ".png"))
                ]
                if not all_files:
                    logger.error(f"画像ファイルが見つかりませんでした: {photo_dir}")
                    if os.path.exists(STATE_FILE):
                        os.remove(STATE_FILE)
                    time.sleep(60)
                    continue

                random.shuffle(all_files)
                display_queue = all_files
                total_in_cycle = len(display_queue)

            image_path = display_queue.pop(0)

            # カウンタをインクリメント
            display_counter += 1

            processed_image = prepare_image(
                image_path,
                inky_display,
                display_counter,
            )

            if processed_image is None:
                logger.error(
                    f"画像処理に失敗したためスキップします: {os.path.basename(image_path)}"
                )
            else:
                max_retry = 3
                for attempt in range(1, max_retry + 1):
                    try:
                        inky_display.set_image(processed_image)
                        inky_display.show()
                        logger.info(
                            f"表示に成功しました: {os.path.basename(image_path)} (attempt={attempt})"
                        )
                        logger.info(f"表示カウンタ: {display_counter}")
                        save_display_counter(display_counter)
                        save_state(display_queue, total_in_cycle)
                        update_heartbeat()
                        break
                    except Exception as e:
                        logger.error(f"表示エラー (attempt={attempt}): {e}")
                        time.sleep(5)
                else:
                    logger.error(
                        f"表示に連続して失敗しました。画像をスキップします: {os.path.basename(image_path)}"
                    )

            interval = CONFIG["INTERVAL_SECONDS"]
            logger.info(f"次の表示まで {interval}秒 待機します...")
            time.sleep(interval)

        except KeyboardInterrupt:
            logger.info("ユーザーの操作により中断されました")
            break
        except Exception as e:
            logger.error(f"予期しないエラーが発生しました: {e}")
            logger.error(traceback.format_exc())
            time.sleep(10)

    if logger:
        logger.info("=== プログラムを正常終了します ===")


if __name__ == "__main__":
    main()
