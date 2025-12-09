#!/usr/bin/env python3
"""
Raspberry Pi の電圧/サーマルスロットリング状態を監視し、
状態に変化があった場合 ntfy に通知するスクリプト。

- vcgencmd get_throttled の結果を取得
- 前回状態と比較して変化があれば ntfy.sh に通知
- ログは ~/.logs/throttled_monitor.log
- 状態ファイルは ~/.cache/throttled_state.json
"""

import subprocess
import logging
import os
import json
from datetime import datetime
from urllib import request, error as urlerror

# ===== 設定 =====
NTFY_URL = "https://ntfy.sh/hO5qZAhnDf2srhuP"  # あなた専用トピック
HOSTNAME = os.uname().nodename                 # 例: wc-inky133

LOG_DIR = os.path.expanduser("~/.logs")
LOG_FILE = os.path.join(LOG_DIR, "throttled_monitor.log")

STATE_DIR = os.path.expanduser("~/.cache")
STATE_FILE = os.path.join(STATE_DIR, "throttled_state.json")


def setup_logging():
    os.makedirs(LOG_DIR, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(LOG_FILE),
            logging.StreamHandler()
        ]
    )


def run_vcgencmd_get_throttled():
    """vcgencmd get_throttled を実行し、整数値を返す"""
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"],
            capture_output=True,
            text=True,
            check=True,
        )
        output = result.stdout.strip()
        logging.info(f"vcgencmd output: {output}")

        if "=" not in output:
            raise ValueError("Unexpected vcgencmd output format")

        _, value_str = output.split("=", 1)
        value_str = value_str.strip()

        if value_str.startswith("0x"):
            value = int(value_str, 16)
        else:
            value = int(value_str)

        return value, output

    except Exception as e:
        logging.error(f"vcgencmd get_throttled error: {e}")
        return None, None


def decode_flags(value: int):
    """get_throttled のビットをデコードする"""
    flags = {
        "under_voltage_now": bool(value & 0x00001),
        "arm_freq_capped_now": bool(value & 0x00002),
        "throttled_now": bool(value & 0x00004),
        "soft_temp_limit_now": bool(value & 0x00008),

        "under_voltage_past": bool(value & 0x10000),
        "arm_freq_capped_past": bool(value & 0x20000),
        "throttled_past": bool(value & 0x40000),
        "soft_temp_limit_past": bool(value & 0x80000),
    }
    return flags


def load_previous_state():
    os.makedirs(STATE_DIR, exist_ok=True)
    if not os.path.exists(STATE_FILE):
        return None

    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
        return state
    except Exception as e:
        logging.warning(f"state load error: {e}")
        return None


def save_state(value, flags):
    state = {
        "value": value,
        "flags": flags,
        "timestamp": datetime.now().isoformat()
    }
    try:
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
    except Exception as e:
        logging.error(f"state save error: {e}")


def send_ntfy(title: str, message: str, tags=None, priority=None):
    """ntfy.sh に通知を送信する（タイトルは英語のみ）"""
    data = message.encode("utf-8")
    headers = {"Title": title}
    if tags:
        headers["Tags"] = ",".join(tags)
    if priority:
        headers["Priority"] = str(priority)

    req = request.Request(NTFY_URL, data=data, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=10) as resp:
            logging.info(f"ntfy sent: HTTP {resp.status}")
    except urlerror.URLError as e:
        logging.error(f"ntfy send error: {e}")


def describe_flags(flags):
    """フラグ内容を人間向け日本語メッセージに変換"""
    now_active = []
    past_active = []

    if flags["under_voltage_now"]:
        now_active.append("電圧低下（現在）")
    if flags["arm_freq_capped_now"]:
        now_active.append("CPU周波数制限（現在）")
    if flags["throttled_now"]:
        now_active.append("スロットリング（現在）")
    if flags["soft_temp_limit_now"]:
        now_active.append("温度リミット（現在）")

    if flags["under_voltage_past"]:
        past_active.append("過去に電圧低下あり")
    if flags["arm_freq_capped_past"]:
        past_active.append("過去に周波数制限あり")
    if flags["throttled_past"]:
        past_active.append("過去にスロットリングあり")
    if flags["soft_temp_limit_past"]:
        past_active.append("過去に温度リミットあり")

    message = ["■ 現在の状態:"]
    if now_active:
        for item in now_active:
            message.append(f"  - {item}")
    else:
        message.append("  - 現在問題なし")

    message.append("\n■ 過去の状態:")
    if past_active:
        for item in past_active:
            message.append(f"  - {item}")
    else:
        message.append("  - 過去フラグなし")

    return "\n".join(message)


def main():
    setup_logging()
    logging.info("===== throttled monitor start =====")

    value, raw_output = run_vcgencmd_get_throttled()
    if value is None:
        logging.error("vcgencmd failed; aborting")
        return

    flags = decode_flags(value)
    prev = load_previous_state()

    logging.info(f"value=0x{value:X}")
    logging.info(f"flags={flags}")

    # 初回は必ず通知
    if prev is None:
        title = f"[{HOSTNAME}] throttled initial"
        body = f"raw: {raw_output}\n\n" + describe_flags(flags)
        send_ntfy(title, body, tags=["raspi", "throttle"], priority=3)
        save_state(value, flags)
        logging.info("初回通知完了")
        return

    # 状態変化チェック
    prev_value = prev.get("value")
    prev_flags = prev.get("flags", {})

    if prev_value != value or prev_flags != flags:
        title = f"[{HOSTNAME}] throttled changed"
        body = (
            f"前回: 0x{prev_value:X} → 今回: 0x{value:X}\n"
            f"raw: {raw_output}\n\n"
            + describe_flags(flags)
        )
        send_ntfy(title, body, tags=["raspi", "throttle", "change"], priority=4)
        logging.info("状態変化 → ntfy 通知送信")

    save_state(value, flags)
    logging.info("===== throttled monitor end =====")


if __name__ == "__main__":
    main()
