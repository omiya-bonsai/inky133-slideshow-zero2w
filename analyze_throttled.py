#!/usr/bin/env python3
"""
Raspberry Pi get_throttled ログ解析スクリプト

~/.logs/throttled_monitor.log を読み込み、
過去数日分の throttled フラグを集計し、
状況サマリと「次にやるべきこと」を出力します。

前提:
  monitor_throttled.py が同じログファイルに
  'flags={...}' 形式の行を出力していること。
"""

import os
import ast
from datetime import datetime
from collections import Counter

# ログファイルパス（monitor_throttled.py と揃える）
LOG_FILE = os.path.expanduser("~/.logs/throttled_monitor.log")


def parse_log():
    """
    ログファイルから flags 行をパースして統計情報を返す
    """
    if not os.path.exists(LOG_FILE):
        print(f"ログファイルが見つかりません: {LOG_FILE}")
        print("monitor_throttled.py が正しく動作しているか確認してください。")
        return None

    counters = Counter()
    timestamps = []

    with open(LOG_FILE, "r", encoding="utf-8") as f:
        for line in f:
            if "flags=" not in line:
                continue

            # 先頭のタイムスタンプ部分を取得（例: 2025-12-07 14:35:41）
            try:
                ts_str = line.split(" - ", 1)[0]  # "2025-12-07 14:35:41,882"
                ts_str = ts_str.split(",")[0]    # "2025-12-07 14:35:41"
                ts = datetime.strptime(ts_str, "%Y-%m-%d %H:%M:%S")
                timestamps.append(ts)
            except Exception:
                # タイムスタンプ解析失敗は無視
                ts = None

            # flags 辞書部分を抽出
            try:
                flags_str = line.split("flags=", 1)[1].strip()
                # 末尾の改行を除去
                if flags_str.endswith("\n"):
                    flags_str = flags_str[:-1]
                flags = ast.literal_eval(flags_str)
            except Exception:
                # パースに失敗したらスキップ
                continue

            # True のフラグのみカウント
            for key, value in flags.items():
                if value:
                    counters[key] += 1

            counters["samples"] += 1

    if counters["samples"] == 0:
        print("flags 行が 1 件も見つかりませんでした。")
        print("monitor_throttled.py のログ出力形式を確認してください。")
        return None

    return {
        "counters": counters,
        "timestamps": timestamps,
    }


def print_summary(stats):
    counters = stats["counters"]
    timestamps = stats["timestamps"]

    samples = counters["samples"]
    first_ts = min(timestamps)
    last_ts = max(timestamps)
    duration_days = (last_ts - first_ts).total_seconds() / 86400.0

    print("====================================")
    print("  get_throttled ログ解析サマリ")
    print("====================================")
    print(f"サンプル数        : {samples}")
    print(f"期間              : {first_ts} 〜 {last_ts}")
    print(f"おおよその日数    : {duration_days:.1f} 日分")
    print()
    print("フラグごとの True 回数:")
    for key in [
        "under_voltage_now",
        "under_voltage_past",
        "arm_freq_capped_now",
        "arm_freq_capped_past",
        "throttled_now",
        "throttled_past",
        "soft_temp_limit_now",
        "soft_temp_limit_past",
    ]:
        print(f"  {key:23s}: {counters.get(key, 0)}")

    print()
    print("====================================")
    print("  次にやるべきこと（提案）")
    print("====================================")

    uv_now = counters.get("under_voltage_now", 0)
    uv_past = counters.get("under_voltage_past", 0)
    thr_now = counters.get("throttled_now", 0)
    thr_past = counters.get("throttled_past", 0)
    temp_now = counters.get("soft_temp_limit_now", 0)
    temp_past = counters.get("soft_temp_limit_past", 0)

    # 閾値は経験則ベースでざっくり決める
    uv_ratio = uv_past / samples if samples > 0 else 0.0
    thr_ratio = thr_past / samples if samples > 0 else 0.0

    # ケース1: 低電圧・スロットリングほぼゼロ
    if uv_now == 0 and uv_past == 0 and thr_now == 0 and thr_past == 0 and temp_now == 0 and temp_past == 0:
        print("◆ 電圧・温度・クロックいずれも問題になっていないようです。")
        print("  ・電源品質は概ね十分と考えられます。")
        print("  ・もし Inky Impression が固まる場合は、")
        print("    → ライブラリのバグ / SPI 通信 / ケーブル接触不良 などを疑った方が良さそうです。")
        print("  ・次の一手としては、描画まわりのログ強化や、通信エラー検知を検討してください。")
        return

    # ケース2: 低電圧が「ごくたまに」出ている
    if uv_past > 0 and uv_ratio < 0.01:  # 1% 未満
        print("◆ 過去に 1 回以上の under_voltage が記録されていますが、頻度はかなり低いです。")
        print("  ・現在の電源でも大きな問題はなさそうですが、")
        print("    → 稀にピーク電流時に電圧が落ちている可能性があります。")
        print("  ・次の一手（優先度: 中）")
        print("    - ケーブルを短く・太いものにする")
        print("    - 予備の AC アダプタで同じ現象が出るか比較する")
        print("  ・頻繁に e-paper が固まるようなら、Pi4 や Pi5 への移行も選択肢です。")

    # ケース3: 低電圧がそこそこ〜頻発
    if uv_ratio >= 0.01:
        print("◆ under_voltage がそこそこの頻度で発生しています。")
        print(f"  ・総サンプルに対する under_voltage_past の割合: {uv_ratio*100:.1f}%")
        print("  ・これは電源余裕があまり無いことを意味します。")
        print("  ・次の一手（優先度: 高）")
        print("    1) Zero2W 専用に、品質の良い 5V/3A クラスの電源＋短めのケーブルに変更")
        print("    2) Inky Impression を更新するタイミングで、他の高負荷処理を避ける（cron/systemd の調整）")
        print("    3) それでも改善しない場合、Pi4 / Pi5 など電源周りに余裕のあるボードへの移行を検討")

    # ケース4: スロットリング・温度制限も出ている
    if thr_past > 0 or temp_past > 0:
        print()
        print("◆ クロック制限(throttled) または 温度上限(soft_temp_limit) も記録されています。")
        print("  ・CPU 負荷が高いタスク（画像処理・他のサービス）が重なっていないか確認してください。")
        print("  ・ケースによっては、")
        print("    → 冷却（ヒートシンク / ファン）")
        print("    → 重いスクリプトの実行時間帯の分散")
        print("    なども検討対象になります。")

    print()
    print("◆ 共通の次ステップ（提案）")
    print("  - 今後も monitor_throttled.py を継続運用し、電源やボードを変更した後も同じ解析を行う。")
    print("  - before/after で under_voltage / throttled の回数がどう変化したかを比較すると、")
    print("    → 変更の効果が客観的に評価できます。")


def main():
    stats = parse_log()
    if stats is None:
        return
    print_summary(stats)


if __name__ == "__main__":
    main()
