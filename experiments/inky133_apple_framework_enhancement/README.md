# Inky133 Apple Framework Enhancement

Inky133 production向けに、Apple純正Frameworkで写真用のResize Only RGBと4種類の背景effectを事前生成します。IllustrationはResize Only RGBだけを生成します。Style Transferは含みません。

## 処理構成

```text
original/photo または original/illustration
  -> ImageIO / Core Imageでorientation適用
  -> VisionでForeground・Person・Face・Attention Saliency解析
  -> Accelerate（vImage / vDSP）でmask面積・重心を計測
  -> area・相対サイズ・近接性・face・scoreから主要人物グループを選択
  -> 採用したPerson maskをOR結合してCombined People Maskを生成
  -> 選択済み人物に対応するfaceのsoft ellipseをmaximum合成
  -> 既存Gaussian featherを適用
  -> photoへProduction SAT（Saturation 1.30 / Contrast 1.15 / Brightness 0.00）を適用
  -> 選択人物の顔＋首上部だけContrast 1.05でsoft合成
  -> Core Image（Metal backend）でsubject/background effectを合成
  -> 1600x1200 contain（白背景、cropなし）
  -> CoreGraphics / ImageIOでRGB PNG書き出し
```

入力はPhotos.appから書き出したファイルを正本とします。PhotoKitからライブラリを再取得すると、写真ライブラリ権限、asset照合、書き出し済みファイルとの二重管理が発生するため、この実験の実行経路では使用しません。PhotoKitを使うのは、将来Photos local identifierを入力metadataへ保存し、assetを一意に対応付けられるようになった段階に限定します。

## Effect Engine

| No. | ディレクトリ | 表示名 | 適用先 |
|---:|---|---|---|
| 00 | `resize-only-rgb/` | Resize Only RGB | 基準画像 |
| 02 | `background-noir/` | Background Noir | 背景 |
| 05 | `background-blur/` | Background Blur | 背景 |
| 07 | `background-twirl/` | Background Twirl | 背景 |
| 08 | `background-crystallize/` | Background Crystallize | 背景 |

`person-color`、`person-comic`、`background-edgework`、`person-bump`は評価結果により通常生成から外しました。Swift側の`experimentalEffects`と`renderEffect()`実装は残してあり、将来は定義を通常の`effects`へ移すだけで再評価できます。

採用値はBlur `20.0`、Twirl radius ratio `0.90` / angle `3.0`、Crystallize `56.0`です。CLIで明示した値は従来どおり優先されます。主役の信頼度が閾値未満なら、subject必須effectも必ず生成しますが内容はResize Only RGBとpixel一致するfallbackになります。失敗理由とconfidenceはmetadataに残ります。

Color Calibrationの実機評価結果により、photoの標準色補正にはSAT-X3相当の`Production SAT`を正式採用しています。通常生成では`CIColorControls`をSaturation `1.30`、Contrast `1.15`、Brightness `0.00`で一度だけ適用し、その共通画像からResize Only RGBと各effectを生成します。SAT-X4は多くの写真で良好だった一方、一部で肌色や赤が強くなりすぎたため、より穏やかなSAT-X3を標準としました。SAT-HおよびSAT-X1〜X4という名称はCalibration比較専用です。Illustrationは従来どおり色補正なしのResize Only RGBです。

人物写真では、Primary People Groupへ選択された人物に対応するfaceだけ、Saturation `1.30`、Contrast `1.05`、Brightness `0.00`で局所補正します。顔bbox内のsoft ellipseへ、下方向へ短く減衰する首上部ellipseを合成し、全体のProduction SATへ重ねます。背景人物、未選択人物、顔未検出、Person以外のForeground fallbackには適用しません。background effect保護用face-aware maskとは役割を分けています。

## Build

Swift helperは初回またはsource更新時に自動ビルドされます。macOS 15以降が必要です。

```bash
python3 experiments/inky133_apple_framework_enhancement/build.py --limit 5
python3 experiments/inky133_apple_framework_enhancement/build.py --input original/photo/sample.jpg
python3 experiments/inky133_apple_framework_enhancement/build.py --workers 2
python3 experiments/inky133_apple_framework_enhancement/build.py --validate
```

通常buildは`source_sha256`、`swift_helper_hash`、各versionと出力PNGを照合します。変更のないphotoは5出力、illustrationは1出力をまとめてskipします。TTYでは進捗率、完了source数、生成数、失敗数、経過時間、ETAを1行更新し、非TTYでは約10%間隔のplain textを出します。

```text
output/experiments/inky133-apple-framework-enhancement/
  metadata.json
  resize-only-rgb/
  background-noir/
  background-blur/
  background-twirl/
  background-crystallize/
```

1枚だけHTML比較を作る場合:

```bash
python3 experiments/inky133_apple_framework_enhancement/comparison.py \
  --input original/photo/sample.jpg
```

## Color Calibration Mode

Inky133実機で、同じ1600×1200写真の同一座標を400px幅の縦4stripeへ分け、`RAW / VIB / SAT / TONE`を比較できます。4枚の縮小画像ではなく、画面全体のgeometryは一枚の写真として連続します。Core Image処理はMacで行い、Piはpre-rendered stripeのcrop/pasteと専用label描画だけを行います。

Calibrationの対象は`photos/apple-effects/calibration/manifest.json`に登録されたsourceだけです。通常スライドショーの現在画像、queue、再生順とは独立し、manifest sourceを固定ソートした専用リストとして循環します。通常表示画像はCalibration終了時の復帰用にだけ保持します。

容量を抑えるため、全ライブラリへvariantを追加しません。校正したいphotoだけを明示して、既存Resize Only RGBから14 assets（RAW 1枚、VIB 3枚、SAT 7枚、TONE 3枚）を生成します。

```bash
python3 -m experiments.inky133_apple_framework_enhancement.color_calibration \
  --input original/photo/sample.jpg

python3 -m experiments.inky133_apple_framework_enhancement.color_calibration \
  --input original/photo/sample.jpg \
  --resize-root /Volumes/NVME512/inky-photo-pipeline-backup/inky133-apple-framework-enhancement/resize-only-rgb

python3 -m experiments.inky133_apple_framework_enhancement.sync_color_calibration \
  --dry-run --restart
python3 -m experiments.inky133_apple_framework_enhancement.sync_color_calibration \
  --restart
```

`--resize-root`を省略すると従来の`output/experiments/inky133-apple-framework-enhancement/resize-only-rgb/`を使用します。明示時は指定rootと同じ親の`metadata.json`から既存のsource→output対応を読み、独自のファイル名推測や内蔵SSDへのfallbackは行いません。symlinkと`/Volumes/...`の外付けvolumeを利用できますが、未mount時はエラーで停止します。

assetsは`output/experiments/inky133-color-calibration/`、Piでは`photos/apple-effects/calibration/`へ保存します。Calibration専用syncは、Apple effectのPi runtime一式、systemd unit、Calibration assetsを同じdeployで同期し、`--restart`指定時は`inky133-apple-effects.service`のactive確認まで行います。これによりruntimeとassetsの世代不一致を防ぎます。manifestにtargetが1件もない場合だけC操作を安全に無視します。通常表示がphotoかillustrationかはCalibration target選択へ影響しません。

操作:

- C short: manifest先頭targetで校正開始 / 次のtargetへ切替
- C long: 校正終了し、直前の通常表示へ復帰
- D short（標準比較）: `S → M → H → S`（初期値M）
- D long: 標準比較 / SAT比較を切替
- D short（SAT比較）: SAT group 1 / 2を切替
- A / B / long-B: 従来どおりnext / reboot / poweroff

Inky Impression 13.3のGPIO割当は`A=GPIO5`、`B=GPIO6`、`C=GPIO25`、`D=GPIO24`です。旧Inky系で一般的な`C=GPIO16`は13.3では使用しません。EL133UF1 driverが`GPIO26=CS0`、`GPIO16=CS1`として両方を必要とするためです。起動時はインストール済みdriverのCS定数を読み、C/Dとの競合がないことを検証してからbutton監視を開始します。

mode aliasは、無補正の`RAW`、`CIVibrance`の`VIB`、`CIColorControls`の`SAT`、`CIToneCurve`の`TONE`です。stripe上部へ`RAW`、`VIB-M`等を、右下へ`CAL P1 M`を表示します。通常のCapture Date、Updated/Uptime、family age、effect名overlayは校正中には重ねません。

stripe patternはP1へ固定します。

- P1: `RAW | VIB | SAT | TONE`

SAT比較:

- SAT group 1: `RAW | SAT-H | SAT-X1 | SAT-X2`
- SAT group 2: `RAW | SAT-H | SAT-X3 | SAT-X4`

VIBはS/M/H=`0.20 / 0.35 / 0.50`です。SATはS=`1.10/1.03/0.00`、M=`1.20/1.06/0.00`、H=`1.30/1.10/0.00`（saturation/contrast/brightness）です。TONE control pointsはmanifestへ記録します。

拡張SATはX1=`1.35/1.10/0.00`、X2=`1.40/1.10/0.00`、X3=`1.30/1.15/0.00`、X4=`1.35/1.15/0.00`です。旧manifestは標準比較のまま読み込めます。SAT比較を使うtargetだけCalibration Builderで再生成してください。

実機でSAT-X4を数十枚評価した結果、一部の肌色や赤が強くなりすぎたため、Production側では一段穏やかなSAT-X3を`Production SAT`として採用しています。Calibration側のSAT-HとX1〜X4は評価履歴・再比較用として残し、通常生成のpreset選択には使用しません。

## Primary People Groupとmetadata

Person instanceを個別候補として扱い、最高score候補をanchorにします。面積`0.012`未満、最大候補の`18%`未満、score`0.34`未満は除外し、残りは人物同士の中心距離・水平gap・垂直overlap、face overlap、十分な面積とscoreからPrimary People Groupへ追加します。複数候補時のanchor閾値は`0.46`、単独候補は従来どおり`0.52`です。採用maskはpixel単位のmaximum（論理和相当）で結合します。Productionでは、選択済みPersonに対応するVision faceだけをsoft radial ellipseで追加保護し、その後に既存featherを一度適用します。顔未検出の人物やForeground fallbackは従来maskを維持します。

遠景の小人物を無条件には保護しません。一方、離れていても面積`0.025`以上、最大候補の`25%`以上、score`0.40`以上なら共同主役として保護します。これより弱くても無視するには大きい人物が残り、1人だけを保護する結果になる場合は、背景effectを適用せずResize Only RGBへfallbackします。Person instanceがない場合だけ、うさぎ等に対応する既存Foreground fallbackを維持します。

1枚の選択結果をproduction buildと分離して確認できます。

```bash
python3 -m experiments.inky133_apple_framework_enhancement.debug_subject_selection \
  --input original/photo/sample.jpg
```

`output/debug/inky133-primary-people-group/<timestamp>/`へ、緑枠が採用・赤枠が除外の`source-overlay.png`、白が保護領域の`combined-people-mask.png`、候補ごとの理由を含む`report.json`、Swift全体レポートを出力します。通常buildではdebug画像を生成しません。

人物境界だけを比較する場合は、選択ロジックを変えずにCombined People Maskのdilationを4段階生成できます。

```bash
python3 -m experiments.inky133_apple_framework_enhancement.debug_subject_selection \
  --input original/photo/sample.jpg \
  --compare-mask-dilation
```

`dilation/0px`〜`3px`へmask、Resize Only RGB、Noir、Blur、Twirl、Crystallizeを出力します。順序は`OR結合 → CIMorphologyMaximum → Gaussian feather → composite`です。半径は最終1600×1200上のpixelとして指定し、Core Image処理時にはcontain scaleでsource画像上のpixelへ換算します。例えばscaleが`0.2667`なら、最終1pxはsource上の約3.75pxです。正確な換算値は`dilation/report.json`へ保存されます。

`0px`はface-aware採用前の`OR結合 → Gaussian feather`を再現するlegacy baselineです。Productionには1〜3pxのdilationを適用しません。

人物内部のsoft mask confidenceを比較する場合:

```bash
python3 -m experiments.inky133_apple_framework_enhancement.debug_subject_selection \
  --input original/photo/sample.jpg \
  --compare-mask-confidence
```

`confidence/`へ`baseline`、`boost-weak`、`boost-strong`、`face-aware`、`boost-plus-face`を生成します。Boostは`output = input^power`で、weakは`0.70`、strongは`0.45`です。0と1を維持したまま、中間値を白側へ持ち上げます。Face-awareは選択済み人物bbox内に中心があるVision faceだけを対応付け、顔矩形より少し広いsoft ellipseをCombined People Maskへmaximum合成します。顔がない人物の選択やmaskは変更しません。Production renderer `1.4`は`face-aware`とpixel一致し、`baseline`は採用前の比較用として残します。

`confidence/report.json`にはcurve値、各選択人物bbox内のraw mask統計、対応する顔bbox内のmean・min/max・percentileを記録します。Confidence boost、boost-plus-face、dilationはdebug専用であり、production defaultには採用していません。dilation比較との同時指定も可能です。

metadataには少なくとも次を保存します。

- `fallback`, `fallback_reason`, `subject_confidence`
- `renderer_version`, `vision_version`, `effect_version`
- `subject_selection_version`, `profile_version`
- `swift_helper_hash`, `source_sha256`
- Vision検出数、capture date、category、display mode、weight
- `selectedPersonCount`, `selectedInstanceIndexes`, `candidateCount`
- `groupConfidence`, 候補ごとの`selected` / `selectionReason`

重みは既存方針を変えず、Resize Only RGBが`5.0`、photoの他4 effectが各`0.625`です。Illustrationのmetadata entryはResize Only RGBだけで、effectディレクトリ違いの重複はありません。ランダム適用ロジック自体は変更していません。

## PiへDeployして評価

この実験はproductionの`photos/auto`、metadata、queueを使いません。

```bash
python3 experiments/inky133_apple_framework_enhancement/sync_to_pi.py --dry-run
python3 experiments/inky133_apple_framework_enhancement/sync_to_pi.py --restart
ssh inky133 'journalctl -u inky133-apple-effects.service -f'
```

`--restart`はproduction slideshow、Style Evaluation、Phase 3実験を停止してから、この実験serviceだけを起動します。productionへ戻す場合:

```bash
ssh inky133 'sudo systemctl stop inky133-apple-effects.service && sudo systemctl start inky-slideshow.service'
```

PiはMacで完成したRGB PNGを開き、写真では撮影日、Updated/Uptime、表示モード/家族年齢の3キャプションを四隅の重複しない位置へランダム配置します。IllustrationのOverlayは変更しません。Overlay追加後は既存の`set_image()` / `show()`へ渡し、resize、crop、quantize、dither、色補正は行いません。

家族年齢はHis（1978-06-01）、Ah-ca（1978-09-22）、Rin（2012-12-02）から撮影日時点で算出します。His/Ah-caは`His 48y` / `Ah-ca 47y`、Rinは3歳未満だけ`Rin 2y 11m`、3歳以上は`Rin 3y`のASCII表記です。Illustrationでは撮影日時、家族年齢、effect名を表示せず、既存形式の`Updated`（表示時刻）と`Uptime`だけを表示します。

このMacの標準`openrsync`はrsync 2.6.9互換で`--info=progress2`をサポートしないため、対話端末でのDeployには対応済みの`--progress`を自動追加します。非TTYではprogress optionを付けずログを壊しません。各Deploy stepのstarted/completed表示と終了コード判定は従来どおりです。

## 安全境界

- productionの`profiles/`、`pipeline.py`、`preprocess.py`、`metadata.py`、`sync.py`、`main.py`は変更しません。
- experiment outputとmetadataは`output/experiments/`以下だけです。
- Deployは`photos/apple-effects/`だけを対象にし、`--delete`を使いません。
- Google/Magenta、TensorFlow、Core ML Style Transfer、OpenCVは使用しません。
- 将来のStyle TransferはEffectDefinition相当の新しいengineとして追加し、既存effect metadata/versionを独立して更新します。

## トラブルシューティング

`show()`が完了しても物理パネルが更新されない場合、アプリの例外とpanel controllerのhangを分けて確認します。journalと表示sourceが進んでいるのにpanelだけ停止している場合は、service停止後にInky133を完全電源断し、電源ケーブルを抜いて数十秒待ってから再投入してください。
