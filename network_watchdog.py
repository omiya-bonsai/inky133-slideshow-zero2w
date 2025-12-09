#!/usr/bin/env python3
import subprocess
import time
import os
from datetime import datetime
import json

LOG_DIR = os.path.expanduser("~/.logs")
LOG_FILE = os.path.join(LOG_DIR, "network_watchdog.log")
os.makedirs(LOG_DIR, exist_ok=True)

# ここは必要に応じて変更
GATEWAY_IP = "192.168.3.1"

# ntfy 用。monitor_throttled.py と同じ環境変数を想定
NTFY_URL = os.environ.get("NTFY_TOPIC_URL", "").strip()


def log(msg: str):
    line = f"{datetime.now().isoformat(timespec='seconds')} [network-watchdog] {msg}"
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def send_ntfy(title: str, message: str, tags=None, priority: int = 3):
    if not NTFY_URL:
        log(f"ntfy URL 未設定のため通知スキップ: {title}")
        return
    import urllib.request

    body = {
        "title": title,
        "message": message,
    }
    if tags:
        body["tags"] = tags
    if priority:
        body["priority"] = priority

    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        NTFY_URL,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            log(f"ntfy sent: HTTP {resp.status}")
    except Exception as e:
        log(f"ntfy error: {e}")


def ping_host(host: str, count: int = 3, timeout: int = 2) -> bool:
    try:
        result = subprocess.run(
            ["ping", "-c", str(count), "-W", str(timeout), host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        return result.returncode == 0
    except Exception as e:
        log(f"ping 実行エラー: {e}")
        return False


def restart_wifi():
    # NetworkManager 前提。違っていたらここだけ調整。
    cmds = [
        ["nmcli", "device", "disconnect", "wlan0"],
        ["nmcli", "device", "connect", "wlan0"],
    ]
    for cmd in cmds:
        log(f"実行: {' '.join(cmd)}")
        try:
            subprocess.run(cmd, check=False)
        except Exception as e:
            log(f"コマンド失敗: {cmd} -> {e}")


def main():
    log("===== network watchdog start =====")

    if ping_host(GATEWAY_IP):
        log(f"ping OK: {GATEWAY_IP}")
        return

    log(f"ping NG: {GATEWAY_IP}。Wi-Fi 再接続を試みます。")
    restart_wifi()
    time.sleep(10)

    if ping_host(GATEWAY_IP):
        log("再接続後の ping は成功しました。")
        send_ntfy(
            "Raspberry Pi Wi-Fi 再接続",
            "network_watchdog が Wi-Fi を再接続しました。（ping 復旧）",
            tags=["raspi", "network"],
            priority=3,
        )
        return

    log("再接続後も ping に失敗しました。")
    send_ntfy(
        "Raspberry Pi ネットワーク障害",
        "network_watchdog で Wi-Fi 再接続を試みましたが復旧しませんでした。",
        tags=["raspi", "network", "error"],
        priority=4,
    )

    # いきなり自動再起動は怖ければ、まずはコメントアウトして様子を見る
    # log("システム再起動を試みます...")
    # subprocess.run(["/usr/bin/systemctl", "reboot", "-i"], check=False)


if __name__ == "__main__":
    main()
