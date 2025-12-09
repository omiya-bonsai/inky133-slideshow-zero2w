# Inky 13.3" Slideshow on Raspberry Pi Zero 2W

Pimoroni Inky Impression 13.3" / Inky EL133UF1 を **Raspberry Pi Zero 2 W** で常時運用するための、
スライドショー & 監視スクリプト一式です。

- 画像スライドショー（EXIF の撮影日・経過時間・表示カウンタのオーバーレイ付き）
- Inky パネル単体テスト
- 電圧低下 / スロットリング監視（`vcgencmd get_throttled`） + ntfy 通知
- スライドショー用ハートビート & watchdog（ハング時に自動再起動）
- 画像の事前リサイズ用 `preprocess_photos.py`
- 将来のネットワーク監視用 `network_watchdog.py`（WIP）

主に Zero 2 W での運用を想定していますが、Pi 4 / Pi 5 でも利用可能です。

---

## ディレクトリ構成

```text
inky133-slideshow/
  ├── slideshow.py                  # メインのスライドショー本体
  ├── preprocess_photos.py          # 事前リサイズ用スクリプト
  ├── test_panel.py                 # Inky パネル単体テスト
  ├── monitor_throttled.py          # get_throttled ログ & ntfy 通知
  ├── analyze_throttled.py          # throttled ログ解析 & 次の一手提案
  ├── watch_slideshow_heartbeat.py  # ハートビート監視 & 自動再起動
  ├── network_watchdog.py           # ネットワーク監視（今後拡張予定）
  ├── photos_raw/                   # 元画像置き場（Git 管理外）
  ├── photos/                       # リサイズ後画像（Git 管理外）
  ├── tmp/, waste/                  # 一時ファイル等（Git 管理外）
  ├── .env                          # 設定ファイル（手動作成）
  ├── .gitignore
  └── LICENSE
```

---

## 必要環境

- Raspberry Pi OS (Bookworm) on Raspberry Pi Zero 2 W
- Python 3.11 以上
- Pimoroni Inky ライブラリ
- そのほか Python ライブラリ:
  - `Pillow`
  - `piexif`
  - `python-dotenv`
- （任意）EXIF チェック用:
  - `exiftool`

仮想環境は例として `~/.virtualenvs/pimoroni` を使用しています。

```bash
# 例: 仮想環境作成
python3 -m venv ~/.virtualenvs/pimoroni
source ~/.virtualenvs/pimoroni/bin/activate

pip install pillow piexif python-dotenv inky
```

---

## .env の設定

`slideshow.py` と同じディレクトリに `.env` を作成します。

```env
# スライドショーで使用する画像フォルダ（このフォルダ内の .jpg/.jpeg/.png をランダム表示）
PHOTO_DIR="photos/"

# 画像切り替え間隔（秒）
# 例: 1800 = 30分, 1200 = 20分, 3000 = 50分
INTERVAL_SECONDS=1800

# 日付・カウンタオーバーレイ用フォント
# 未設定なら DejaVu Sans Bold を利用
# FONT_PATH="/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc"
```

- `PHOTO_DIR` は `slideshow.py` からの相対パスでも絶対パスでも構いません。
- 設定変更後は `systemctl restart inky-slideshow` で反映します（`.env` の変更に `daemon-reload` は不要）。

---

## 1. 画像の事前リサイズ（任意だが推奨）

Zero 2 W の負荷を下げるために、あらかじめ 1600x1200 にトリミング・リサイズした JPEG を `photos/` に用意します。

1. 元画像を `photos_raw/` にコピー
2. `preprocess_photos.py` を実行

```bash
cd ~/inky133-slideshow
source ~/.virtualenvs/pimoroni/bin/activate

mkdir -p photos_raw photos
# ここに元画像を置く
# cp /somewhere/*.jpg photos_raw/

python3 preprocess_photos.py
```

- `photos_raw/101.jpeg` → `photos/101.jpeg` のように、
  Inky の解像度に合わせてクロップ済み JPEG が生成されます。
- EXIF の撮影日時は元画像からコピーしているため、スライドショーで日付オーバーレイに利用できます。

---

## 2. スライドショー本体（slideshow.py）

### 概要

- Inky Impression 13.3" / Inky EL133UF1 / `inky.auto` に対応した初期化ロジック
- ランダム順で写真を表示しつつ、状態を `~/.cache/slideshow_state_133.json` に保存
- 画面には以下をオーバーレイ表示
  - 撮影日 (EXIF DateTimeOriginal)
  - 現在からの経過時間（xx years ago / xx months ago / Within a month）
  - 「いつ表示されたか」「次回更新予定」のタイムスタンプ（拡張版）
  - 表示カウンタ `#123`（左下）
- ログ:
  - `~/.logs/slideshow_logs/slideshow_133.log`
  - 表示カウンタ: `~/.logs/slideshow_counter_133.txt`
- watchdog 用ハートビート:
  - `/tmp/inky_slideshow_heartbeat`（最終正常更新時刻を記録）

### 手動実行

```bash
cd ~/inky133-slideshow
source ~/.virtualenvs/pimoroni/bin/activate
python3 slideshow.py
```

---

## 3. Inky パネルテスト（test_panel.py）

パネル単体が正常に動作しているかを確認するためのスクリプトです。

- `slideshow.initialize_display()` を流用して Inky を初期化
- 画面を「白 → 黒」の順で強制描画
- 何も変化しない場合は、電源・ケーブル・パネル自体の問題が疑われます

```bash
cd ~/inky133-slideshow
source ~/.virtualenvs/pimoroni/bin/activate
python3 test_panel.py
```

---

## 4. get_throttled 監視 & 解析

### 4-1. monitor_throttled.py

- `vcgencmd get_throttled` を 5 分おきに実行
- 結果を `~/.logs/throttled_monitor.log` に保存
- 状態変化があった場合に ntfy で通知

典型的な systemd 設定例:

```ini
# /etc/systemd/system/monitor-throttled.service
[Unit]
Description=Raspberry Pi get_throttled モニタ (ntfy 通知付き)

[Service]
Type=oneshot
User=bonsai
ExecStart=/usr/bin/python3 /home/bonsai/inky133-slideshow/monitor_throttled.py
```

```ini
# /etc/systemd/system/monitor-throttled.timer
[Unit]
Description=Raspberry Pi get_throttled モニタを5分毎に実行

[Timer]
OnBootSec=1min
OnUnitActiveSec=5min
Unit=monitor-throttled.service

[Install]
WantedBy=timers.target
```

有効化:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now monitor-throttled.timer
```

### 4-2. analyze_throttled.py

- `~/.logs/throttled_monitor.log` を読み込み、
  - サンプル数
  - 期間（日数）
  - 各フラグの True 回数
- を集計し、「次にやるべきこと」を日本語で提案します。

```bash
cd ~/inky133-slideshow
python3 analyze_throttled.py
```

例）
- under_voltage / throttled がゼロ → 電源は概ね問題なし。ライブラリ / SPI / ケーブルの問題を疑う
- under_voltage が頻発 → 電源・ケーブルの強化、更新間隔の延長、Pi4/5 への移行検討、など

---

## 5. ハートビート監視 & 自動再起動

### 5-1. watch_slideshow_heartbeat.py

- `/tmp/inky_slideshow_heartbeat` の最終更新時刻をチェック
- しきい値（デフォルト 7200 秒 = 2時間）より古い場合、
  - `inky-slideshow.service` が active であれば `systemctl restart` 実行
- 通常は 15 分ごとの systemd timer で動かします。

例:

```ini
# /etc/systemd/system/inky-slideshow-watchdog.service
[Unit]
Description=Watchdog for Inky slideshow heartbeat

[Service]
Type=oneshot
User=bonsai
ExecStart=/usr/bin/python3 /home/bonsai/inky133-slideshow/watch_slideshow_heartbeat.py
```

```ini
# /etc/systemd/system/inky-slideshow-watchdog.timer
[Unit]
Description=Run Inky slideshow watchdog every 15 minutes

[Timer]
OnBootSec=5min
OnUnitActiveSec=15min
Unit=inky-slideshow-watchdog.service

[Install]
WantedBy=timers.target
```

有効化:
```bash
sudo systemctl daemon-reload
sudo systemctl enable --now inky-slideshow-watchdog.timer
```

### 5-2. slideshow.py 側のハートビート

- 各表示成功時に `/tmp/inky_slideshow_heartbeat` を更新
- 内容は ISO8601 形式のタイムスタンプ
- watchdog がこれを見て「最近更新されているか」を判断します。

---

## 6. Inky スライドショー本体の systemd 化

例として、以下のような unit を想定：

```ini
# /etc/systemd/system/inky-slideshow.service
[Unit]
Description=Inky Impression 13.3 Slideshow Service
After=network-online.target

[Service]
Type=simple
User=bonsai
WorkingDirectory=/home/bonsai/inky133-slideshow
ExecStart=/home/bonsai/.virtualenvs/pimoroni/bin/python3 /home/bonsai/inky133-slideshow/slideshow.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

有効化:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now inky-slideshow.service
```

---

## 7. network_watchdog.py（今後の拡張）

- 現時点では WIP（実験用）
- 将来的には:
  - ping による疎通監視
  - Wi-Fi 再接続 / dhcpcd の再起動
  - ntfy 通知 or ログ解析
- などの「Zero2W 全体のヘルスチェック」と連携させる予定の枠組みです。

---

## 運用の考え方メモ

- Zero 2 W で Inky 13.3" を運用するのはそこそこ負荷が高め
- 今回の構成では、
  - 画像は事前にリサイズして負荷を軽減
  - 電圧/クロック/温度は `get_throttled` で定期監視
  - スライドショー自体は watchdog で「完全ハング」に備える
- これにより、**電源を入れっぱなしでも「見ていなくても勝手に安定運用してくれる」** ことを目標にしています。

実際の環境では、

- `INTERVAL_SECONDS` の調整（攻める/守る）
- 電源アダプタ・ケーブルの選定
- Pi 4 / Pi 5 への移行

などと組み合わせて、少しずつ「安定運用ポイント」を探っていくことを想定しています。

