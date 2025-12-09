#!/usr/bin/env python3
"""
Inky Slideshow ハートビート監視スクリプト

- /tmp/inky_slideshow_heartbeat の最終更新時刻を確認
- しきい値(THRESHOLD_SECONDS)より古かったら inky-slideshow.service を再起動
"""

import os
import time
import subprocess
from datetime import datetime

HEARTBEAT_FILE = "/tmp/inky_slideshow_heartbeat"
THRESHOLD_SECONDS = 7200  # 2時間

SERVICE_NAME = "inky-slideshow.service"

def log(msg):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"{now} [watchdog] {msg}")

def get_heartbeat_age():
    if not os.path.exists(HEARTBEAT_FILE):
        return None
    try:
        mtime = os.path.getmtime(HEARTBEAT_FILE)
        return time.time() - mtime
    except Exception:
        return None

def is_service_active():
    try:
        result = subprocess.run(
            ["systemctl", "is-active", SERVICE_NAME],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
        return result.stdout.strip() == "active"
    except Exception:
        return False

def restart_service():
    log(f"{SERVICE_NAME} を再起動します...")
    try:
        subprocess.run(
            ["systemctl", "restart", SERVICE_NAME],
            check=False
        )
        log("systemctl restart 実行完了")
    except Exception as e:
        log(f"service restart 失敗: {e}")

def main():
    age = get_heartbeat_age()
    if age is None:
        log("ハートビートファイルが存在しません。初回起動中か、まだ slideshow が動いていない可能性。何もしません。")
        return

    log(f"ハートビートの経過秒数: {age:.1f} 秒")

    if age < THRESHOLD_SECONDS:
        log("ハートビートは正常な範囲内です。何もしません。")
        return

    # しきい値を超えていて、かつサービスが active なら再起動を試みる
    if is_service_active():
        log("ハートビートがしきい値を超え、サービスは active のため、ハングの可能性があります。")
        restart_service()
    else:
        log("サービスが active ではありません。systemd 側で何か操作された可能性があります。再起動は行いません。")

if __name__ == "__main__":
    main()
