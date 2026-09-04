# Inky133 Style Evaluation

Inky133の5種類の人物写真styleを、production slideshowから独立して実機評価する環境です。Pi側の正式配置は次の1系統だけです。

```text
~/inky133-slideshow/experiments/style_evaluation/
```

hyphen表記の旧ディレクトリは使用しません。Deploy前に旧ディレクトリを検出した場合は、安全のため同期を中止します。

## 運用フロー

1. Macで`python3 build_styles.py`を実行します。
2. `python3 experiments/style_evaluation/sync_to_pi.py --dry-run`でDeploy内容を確認します。
3. `python3 experiments/style_evaluation/sync_to_pi.py --restart`で全ファイルを同期します。
4. Deployツールがsystemd unitを更新し、評価serviceをrestartします。
5. `Service active`と`Ready for evaluation`が表示されたことを確認します。
6. `ssh inky133 journalctl -u inky133-style-evaluation.service -f`で評価ログを確認します。
7. `Waiting for evaluation`の後、A/Bボタンで評価を開始します。

## Deploy対象

- `experiments/style_evaluation/`以下のPythonコード、共通display helper、README、style設定、systemd unit
- `output/experiments/inky133-style-evaluation/styles/`
- 実験専用`metadata.json`

productionの`photos/auto`、production metadata、production syncは変更しません。rsyncに`--delete`は使用しません。

## CLI

```bash
# コマンドを表示するだけ。Piへ接続・書き込みしない
python3 experiments/style_evaluation/sync_to_pi.py --dry-run

# inactiveなserviceへ同期だけ行う
python3 experiments/style_evaluation/sync_to_pi.py

# 同期、unit更新、restart、ready確認まで行う正式運用
python3 experiments/style_evaluation/sync_to_pi.py --restart
```

評価serviceがactiveのとき、`--restart`なしのDeployは古いPython processを残すため拒否されます。systemd unitの`Conflicts=inky-slideshow.service`により、production slideshowと評価serviceは同時起動しません。

## 評価ログ

journalには最低限、次の順序で出力されます。

```text
Selected source
Selected style
Overlay created
Display start
Display completed
Waiting for evaluation
Button pressed
Rating saved
Next image
```

評価結果は従来どおりJSON Linesへ追記されます。schemaとボタン動作は変更していません。

## Display経路

`pi/display.py`へInky133の初期化と更新処理を集約しています。productionと同じく`inky.auto.auto(verbose=True)`で検出し、1600×1200を検証して白borderを設定した後、完成済みP-mode画像を変換せず`set_image()`、`show()`の順で渡します。Style Evaluationの評価処理はPimoroni driverを直接操作しません。
