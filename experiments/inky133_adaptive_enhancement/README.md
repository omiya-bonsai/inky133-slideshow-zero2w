# Inky133 Adaptive Enhancement Experiment

Inky133のRGB Resize Only productionを変更せず、Apple純正Frameworkによる安全な自動補正を実機評価する独立環境です。productionの`output/inky133/current/`、`photos/auto/`、`metadata.json`、`inky-slideshow.service`へは書き込みません。

## Architecture

```text
original/photo + original/illustration
  -> Swift CLI
     -> ImageIO / CIImage orientation
     -> Accelerate luminance/chroma analysis
     -> Vision face/person/saliency analysis
     -> Core Image enhancement
     -> Metal-backed CIContext
     -> contain on white 1600x1200 canvas
     -> RGB PNG
  -> Python incremental metadata/build
  -> output/experiments/inky133-adaptive-enhancement/
  -> experimental rsync
  -> inky133-phase3-experiment.service
  -> production Display/queue/buttons/overlay components
  -> Pimoroni set_image()/show()
```

PillowはPNGのmode/size/palette検証、ImageMagickはHTML用original previewだけに使用します。補正本体はCore Imageです。外部AI modelは使用しません。

## Swift CLI

```bash
zsh tools/inky133-enhance/build.sh

tools/inky133-enhance/.build/inky133-enhance \
  --input original/photo/sample.jpg \
  --output /tmp/sample.png \
  --phase phase3 \
  --category photo
```

標準出力は測定値、適用値、Vision結果、Core Image backendを含むJSONです。Metal deviceが利用可能なら`CIContext(mtlDevice:)`を使い、利用できない場合だけCore Image CPU contextへfallbackします。

## Phase 1

固定presetを比較します。

| preset | exposure | contrast | saturation | vibrance | gamma |
|---|---:|---:|---:|---:|---:|
| mild | 0.01 | 1.03 | 1.04 | 0.05 | 1.00 |
| medium | 0.025 | 1.06 | 1.07 | 0.10 | 0.99 |
| strong | 0.04 | 1.09 | 1.11 | 0.15 | 0.98 |

shadow/highlightと弱いtone curveもpresetに連動します。illustrationでは各差分を原則35%へ弱めます。

```bash
python3 -m experiments.inky133_adaptive_enhancement.build \
  --phase phase1 --limit 10
```

## Phase 2

Accelerate/vDSPを使って縮小sampleから以下を測定します。

- mean luminance、32-bin luminance histogram
- mean saturation、16-bin saturation histogram
- luminance standard deviation（contrast）
- shadow / highlight / clipping ratio
- 5–95 percentile dynamic range
- mean RGB

測定値からexposure、brightness、contrast、saturation、vibrance、gamma、shadow、highlightを決めます。全値に小さいmin/max clampがあり、暗い写真を過度に明るくしたり、低彩度写真を過彩度にしたりしません。

## Phase 3

Phase 2へInky133向けの控えめなcontrast、saturation、vibrance、tone curveを加えます。Core Image Auto Adjustmentはcrop、level、red-eyeを無効にし、色・tone系filterだけを最大12%でblendします。その後に解析値由来のclamped補正を適用します。

Visionで人物を検出した場合は色補正を約65%、顔を検出した場合は約45%へ弱めます。これは局所的なskin recoloringではなく、肌色を壊しにくくする全体補正の安全弁です。saliencyは記録しますがPhase 3 v1.0の補正maskには使いません。

illustrationは元色を優先し、adaptive差分を30%、saturationを最大1.04、vibranceを最大0.04、Apple Auto blendを最大3%へ制限します。photo / illustrationともcrop、stretchせず、白背景へcontainします。

## Build

Phase3全件:

```bash
source .venv/bin/activate
python3 -m experiments.inky133_adaptive_enhancement.build \
  --phase phase3 --workers 4
python3 -m experiments.inky133_adaptive_enhancement.build --validate
```

開発時:

```bash
python3 -m experiments.inky133_adaptive_enhancement.build --phase all --limit 5
python3 -m experiments.inky133_adaptive_enhancement.build \
  --phase phase3 --input original/photo/sample.jpg --force
python3 -m experiments.inky133_adaptive_enhancement.build --phase phase3 --dry-run
```

出力:

```text
output/experiments/inky133-adaptive-enhancement/
  metadata.json
  baseline/
  phase1/mild/
  phase1/medium/
  phase1/strong/
  phase2/
  phase3/
  comparison/<timestamp>/index.html
```

incremental stateにはsource SHA-256、size、mtime、helper SHA-256、phase、preset、profile versionを含めます。全件生成後の同条件再実行は`Processed: 0 / Skipped: 1594 / Failed: 0`になります。metadataは全task成功時だけatomic replaceします。

## Comparison HTML

Phase3 metadataから人物、風景、青、緑、赤、暗部、高彩度、illustrationの候補を測定値で選び、Original、Resize Only、Phase1 3 preset、Phase2、Phase3を並べます。

```bash
python3 -m experiments.inky133_adaptive_enhancement.comparison
open output/experiments/inky133-adaptive-enhancement/comparison/*/index.html
```

自動選択は測色やsemantic ground truthではありません。最終代表画像と画質判断は人間が確認してください。

## Pi Deploy

dry-run:

```bash
python3 -m experiments.inky133_adaptive_enhancement.sync_to_pi --dry-run --restart
```

同期と切替:

```bash
python3 -m experiments.inky133_adaptive_enhancement.sync_to_pi --restart
ssh inky133 journalctl -u inky133-phase3-experiment.service -f
```

Phase3 serviceはproduction slideshowの`display.py`、`slideshow.py`、`queue.py`、`buttons.py`、`overlays.py`をimportして再利用します。専用コードはlibrary path、metadata path、queue state suffixを差し替える薄いentry pointだけです。A=next、B短押し=reboot、B長押し=poweroff、自動更新、random queue、overlayはproduction相当です。

実験library pathはentry pointで固定し、production `.env` の汎用`PHOTO_DIR` / `METADATA_FILE` overrideを継承しません。これにより実験serviceが誤って`photos/auto/`を読むことを防ぎます。

`Conflicts=inky-slideshow.service inky133-style-evaluation.service`により同時にpanelへアクセスしません。production unit自体は変更しません。

productionへ戻す:

```bash
ssh inky133 sudo systemctl disable --now inky133-phase3-experiment.service
ssh inky133 sudo systemctl enable --now inky-slideshow.service
```

## Hardware troubleshooting

`Display completed`でも物理panelが変わらない場合、controller hangの可能性があります。アプリ変更を続ける前に次を行います。

1. `sudo poweroff`
2. Pi/Inkyの電源ケーブルを抜く
3. 数十秒待つ
4. ケーブルを戻して起動
5. 対象serviceとjournalを確認

`show()`正常終了だけを物理更新成功とは判断しません。
