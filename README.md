# inky-slideshow

Raspberry Pi上で Inky Impression 13.3" Spectra 6、7.3" Spectra 6、5.7" を1つのコードベースから運用するスライドショーです。端末差分はProfileに集約し、画像の探索、metadata参照、Overlay、ランダムキュー、状態保存、ボタン操作は共通実装です。

画像の前処理はMac側の `inky-photo-pipeline` が完了させます。このプロジェクトはPNGのresize、crop、palette変換、quantize、ditherを行いません。3機種とも完成済みRGBを開き、RGBのままOverlayを描画してInkyドライバへ渡します。

## 対応Profile

| Profile | 解像度 | Production input | Driver | Hostname |
|---|---:|---|---|---|
| `inky133` | 1600×1200 | RGB | `inky.auto:auto` | `wc-inky133` |
| `inky73` | 800×480 | RGB | `inky.auto:auto` | `inky73` |
| `inky57` | 600×448 | RGB | `inky.auto:auto` | `inky57` |

Profileを省略した場合は `inky133` です。

## ディレクトリ構成

```text
inky-slideshow/
├── main.py                 # CLI
├── slideshow.py            # 実行制御・13.3旧service互換entry point
├── display.py              # Inky初期化、set_image、show、DummyDisplay
├── metadata.py             # metadata.jsonの起動時index化
├── overlays.py             # 撮影日・経過日数・Updated・Uptime
├── queue.py                # ランダムqueueと永続state
├── buttons.py              # A/Bボタン
├── config.py               # .env、path、logging
├── profiles/
│   ├── model.py
│   ├── inky133.py
│   ├── inky73.py
│   └── inky57.py
├── assets/
├── tests/
└── watch_slideshow_heartbeat.py
```

同期されるデータは次の2種類だけです。

```text
photos/
├── auto/
│   └── *.png
└── metadata.json
```

`photo/`、`art/`、JPEG、サブディレクトリ内のPNGは表示対象にしません。

## セットアップ

```bash
cd /home/bonsai/inky-slideshow
python3 -m venv ~/.virtualenvs/pimoroni
source ~/.virtualenvs/pimoroni/bin/activate
pip install -r requirements.txt
cp .env.sample .env
```

Macから対象Profile向けに生成・同期した `photos/auto/*.png` と `photos/metadata.json` を配置してください。

## 起動

```bash
python3 main.py --profile inky133
python3 main.py --profile inky73
python3 main.py --profile inky57
```

Profile省略時は次と同じです。

```bash
python3 main.py
```

ハードウェアなしで起動経路を確認する場合は `--dummy` を利用できます。PNGとmetadataは必要ですが、InkyおよびGPIOへアクセスしません。

```bash
python3 main.py --profile inky73 --dummy
```

## .env

`.env` の読込は `config.py` に集約しています。

```env
PHOTO_DIR="photos/auto"
METADATA_FILE="photos/metadata.json"
INTERVAL_SECONDS=1800
FONT_PATH="/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
```

相対pathはプロジェクトroot基準です。Profile固有値は `INKY133_`、`INKY73_`、`INKY57_` prefixで上書きできます。例えば `INKY73_INTERVAL_SECONDS=1200` は7.3だけに適用されます。

## 画像表示フロー

1. `photos/auto/*.png` を列挙する
2. 保存queueを復元し、ライブラリ変更時はqueueを作り直す
3. filenameをkeyとして起動時index済みmetadataをO(1)で参照する
4. Profile別のRGB modeと解像度を検証する
5. 元modeのまま撮影日、経過時間、Updated、Uptimeを描画する
6. `set_image()` と `show()` を呼ぶ
7. queue、display counter、heartbeatを保存する

metadataから `capture_date`（`date`も互換読込）、`source`、`display_mode` を取得します。PNG内のEXIFは参照しません。metadata schemaは変更しません。

## Overlay

13.3 Profileは実運用版と同じ次の値を保持します。

- font size: 20 / date: 24
- margin: 25
- background padding: 15
- text padding: 12
- line spacing: 8
- 日付blockは4隅からrandom選択
- Updated/Uptimeは日付blockの反対側
- RGBの黒文字・白背景を使用

全Profileで黒文字・白背景をRGB値で直接描画し、RGBのままPimoroni driverへ渡します。独自のP-mode再量子化は行いません。

## Buttons

- A（GPIO 5）: 次の画像
- B（GPIO 6）短押し: reboot
- Bを3秒以上長押し: poweroff

GPIO、debounce、長押し時間はProfileにあります。`gpiozero` を利用できない環境ではボタンだけを無効化し、表示処理は継続します。

## State、logging、watchdog

13.3では既存pathを維持します。

```text
~/.cache/slideshow_state_133.json
~/.logs/slideshow_counter_133.txt
~/.logs/slideshow_logs/slideshow_133.log
/tmp/inky_slideshow_heartbeat
```

7.3と5.7はsuffixだけがそれぞれ `_73`、`_57` になります。heartbeat pathは既存watchdog互換のため全Profile共通です。queue stateは一時ファイル作成後の `os.replace()` でatomic保存します。

## systemd

新しい共通配置pathを使うservice例です。

```ini
[Unit]
Description=Inky Slideshow
After=network.target

[Service]
User=bonsai
Group=bonsai
WorkingDirectory=/home/bonsai/inky-slideshow
ExecStart=/home/bonsai/.virtualenvs/pimoroni/bin/python3 /home/bonsai/inky-slideshow/main.py --profile inky133
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
```

7.3/5.7では `--profile` だけを変更します。

現在の13.3環境へ従来どおり `/home/bonsai/inky133-slideshow` として配置する場合、既存serviceの `ExecStart=.../slideshow.py` は変更不要です。`slideshow.py` が互換entry pointとなり、引数なしで `inky133` を選択します。既存watchdogのheartbeat pathとservice名も維持しています。

設定反映:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now inky-slideshow.service
journalctl -u inky-slideshow.service -f
```

## Profileを追加する

1. `profiles/inkyNN.py` を追加する
2. `profiles.model.Profile` の `PROFILE` 定数を定義する
3. 解像度、production `input_mode`、driver、refresh、buttons、Overlay、画像path、metadata path、間隔、hostname、state suffixを指定する
4. `pytest` を実行する
5. Mac側で同じ解像度・paletteのProfileを用意し、実機で1枚検証する

Profileは自動検出されるため、registryや共通pipelineの変更は不要です。Driverは `module:factory` 形式です。自動検出を使わない機種は、その機種用factoryを指定できます。

## テスト

```bash
source ~/.virtualenvs/pimoroni/bin/activate
pip install -r requirements-dev.txt
pytest
```

テストは一時ディレクトリとDummyDisplayを使用し、実画像、稼働state、GPIO、Inkyハードウェアを変更しません。metadata index、queue復元、Profile discovery、DummyDisplay、ボタン、各ProfileのRGB modeと解像度を確認します。

## 7.3 / 5.7の実機導入前チェック

- Raspberry Pi上のPimoroni `inky` が対象panelを `inky.auto` で検出できること
- Mac出力PNGがProfileの解像度とRGB modeであること
- Overlayの文字サイズ、安全余白、4隅すべての視認性
- A/BのGPIO割当が使用するHAT/配線と一致すること
- full refresh時間と既定intervalが運用要件に合うこと
- hostname、systemdの `--profile`、同期先が一致すること

これらはハードウェア固有の最終校正です。共通pipelineの変更は不要で、原則として対象Profileの値だけを調整します。

## Inky133 RGB Resize Only production deployment

Mac側は`original/photo`と`original/illustration`を、cropせず白背景へcontainした1600×1200 RGB PNGとして生成します。両categoryは同じ`photos/auto/`へ同期され、既存の永続random queue、A/Bボタン、自動更新、overlayをそのまま利用します。Pi側でresize、crop、palette変換、quantize、dither、色補正は行いません。

RGB libraryを同期する前に、Inky133 Profileが`input_mode="RGB"`のproduction codeをPiへ配置してください。同期後:

```bash
sudo systemctl enable --now inky-slideshow.service
journalctl -u inky-slideshow.service -n 30 --no-pager
```

Resize Only専用serviceは使用しません。運用対象は従来の`inky-slideshow.service`だけです。

ログで`Mode: RGB`、`Prepared: mode=RGB / size=(1600, 1200) / palette_colours=0`、`Display completed`を確認します。Rollbackではserviceを停止し、Mac側archiveの旧P-mode libraryとmetadata、および`input_mode="P"`のProfileを揃えてからproduction serviceを再開します。

## Inky73 RGB production deployment

Mac側からRGB libraryとmetadataを同期する前に、このRGB対応版slideshow codeをPiへ配置してください。旧版はP-modeだけを受理するため、順序を逆にしないでください。

同期後:

```bash
sudo systemctl restart inky-slideshow.service
journalctl -u inky-slideshow.service -n 30 --no-pager
```

ログで次を確認します。

```text
Profile: inky73
Mode: RGB
Image directory: .../photos/auto
Prepared: mode=RGB / size=(800, 480) / palette_colours=0
Display completed
```

Rollback時はserviceを停止し、Mac側archiveから旧P-mode libraryとmetadataを再同期してから、RGB対応前のslideshow codeへ戻してserviceを起動します。実機確認が完了するまでMac側archiveを削除しないでください。

## Inky57 RGB production deployment

Mac側から600×448 RGB libraryとmetadataを同期する前に、Inky57 Profileが`input_mode="RGB"`の最新版slideshow codeをPiへ配置してください。Pi側ではresize、crop、palette変換、quantize、ditherを行わず、RGBのままOverlay、`set_image()`、`show()`へ進みます。

同期後:

```bash
sudo systemctl restart inky-slideshow.service
journalctl -u inky-slideshow.service -n 30 --no-pager
```

確認するログ:

```text
Profile: inky57
Mode: RGB
Prepared: mode=RGB / size=(600, 448) / palette_colours=0
Display completed
```

Rollback時はserviceを停止し、Mac側Inky57 archiveから旧P-mode libraryとmetadataを復元し、Pi側slideshow codeもP-mode対応版へ戻してから再同期・service起動します。実機確認が完了するまでarchiveを削除しないでください。

## Inky73実験画像を1枚表示する

`show_experiment.py` はcharacterization用PNGを1枚だけ表示して終了する、production slideshowから独立したviewerです。queue、metadata、Overlay、buttons、systemdには接続せず、PNGのresize・色変換・量子化なども行いません。

production serviceと同時にSPI/displayへアクセスしないよう、先にserviceを停止してください。viewer自身はserviceがactiveなら警告しますが、勝手に停止・再開はしません。

```bash
cd ~/inky73-slideshow
source ~/.virtualenvs/pimoroni/bin/activate
sudo systemctl stop inky-slideshow.service
python3 show_experiment.py \
  experiments/characterization/20260810-153352/charts/gray-atlas-checkerboard.png
sudo systemctl start inky-slideshow.service
```

実機へ送らず検証だけ行う場合:

```bash
python3 show_experiment.py --dry-run \
  experiments/characterization/20260810-153352/charts/gray-atlas-checkerboard.png
```

viewerはPNG、P-mode、800x480、paletteの存在、Spectra 6固定paletteの先頭6色、使用indexが0〜5だけであることを確認します。デフォルトでは `experiments/characterization/` 配下だけを受理し、`photos/auto/` などproduction pathは拒否します。別pathを意図的に検証する場合だけ `--allow-any-path` を指定できます。

## Inky73 RGB比較画像を1枚表示する

`show_rgb_experiment.py` はcompareモードが生成した `resize_only.png` をRGBのままInky73へ渡す独立viewerです。RGBからパネル色への変換結果をPimoroniライブラリ側に任せて評価するため、resize、crop、palette変換、quantize、ditherは行いません。

production serviceを停止してから実行してください。

```bash
cd ~/inky73-slideshow
source ~/.virtualenvs/pimoroni/bin/activate
sudo systemctl stop inky-slideshow.service
python3 show_rgb_experiment.py \
  experiments/compare/inky73/20260810-143448/resize_only.png
sudo systemctl start inky-slideshow.service
```

表示せず入力検証だけ行う場合:

```bash
python3 show_rgb_experiment.py --dry-run \
  experiments/compare/inky73/20260810-143448/resize_only.png
```

入力は `experiments/` または `compare/` 配下の `resize_only.png` に限定され、PNG、RGB mode、800×480を検証します。viewerはproduction serviceが動作中なら警告しますが、自動停止・再開はしません。

## Resize OnlyとBaseline P-modeを実機比較する

Mac側のcompare専用syncで転送した同一実行ディレクトリから、RGB参照画像はRGB専用viewer、P-mode baselineは既存の実験viewerで表示します。どちらのviewerも画像加工、queue登録、metadata更新は行いません。

```bash
sudo systemctl stop inky-slideshow.service

# RGB: PimoroniライブラリによるRGBからパネル色への変換を評価
python3 show_rgb_experiment.py \
  experiments/compare/inky73/<timestamp>/resize_only.png

# P-mode: Mac側で完成した固定Spectra 6 palette画像を表示
python3 show_experiment.py \
  experiments/compare/inky73/<timestamp>/A_baseline.png

sudo systemctl start inky-slideshow.service
```

表示せず両方を検証する場合:

```bash
python3 show_rgb_experiment.py --dry-run \
  experiments/compare/inky73/<timestamp>/resize_only.png
python3 show_experiment.py --dry-run \
  experiments/compare/inky73/<timestamp>/A_baseline.png
```

`A_baseline.png` はPNG、P-mode、800×480、Spectra 6固定palette、使用index 0〜5を検証してから、そのまま `set_image()` と `show()` へ渡します。`resize_only.png` はRGB専用viewerだけが受理し、P-mode viewerでは拒否されます。

## RGB前処理A〜Eを実機比較する

Mac側のRGB compare専用syncで転送した5候補は、すべて `show_rgb_experiment.py` でRGBのまま表示します。viewerはPNG、RGB、800×480と許可されたファイル名・実験pathを検証するだけで、画像処理は行いません。

```bash
sudo systemctl stop inky-slideshow.service

python3 show_rgb_experiment.py \
  experiments/compare-rgb/inky73/<timestamp>/A_resize_only.png
python3 show_rgb_experiment.py \
  experiments/compare-rgb/inky73/<timestamp>/B_unsharp.png
python3 show_rgb_experiment.py \
  experiments/compare-rgb/inky73/<timestamp>/C_tone_curve.png
python3 show_rgb_experiment.py \
  experiments/compare-rgb/inky73/<timestamp>/D_tone_unsharp.png
python3 show_rgb_experiment.py \
  experiments/compare-rgb/inky73/<timestamp>/E_tone_unsharp_sat095.png

sudo systemctl start inky-slideshow.service
```

評価ではAより自然か、顔や床のザラつき、ベビーカーや商品棚の細部、黄色い服の彩度、haloやoversharpeningを確認します。最終判断はMac表示ではなく実機Inky73で行います。
