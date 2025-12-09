#!/usr/bin/env python3
"""
Inky Impression / Inky EL133UF1 / auto-detect パネル単体テスト
白 → 黒 の順番で画面を強制描画し、パネルが正常に動作するか確認します。
"""

from PIL import Image
from slideshow import initialize_display   # あなたの slideshow.py の関数を利用

print("=== Inky Impression パネル単体テストを開始します ===")

# --- ディスプレイ初期化 ---
disp = initialize_display()
print("display class:", type(disp))

# --- 白画面の作成と表示 ---
img_white = Image.new("RGB", (disp.width, disp.height), "white")
disp.set_image(img_white)
disp.show()
print("\n[1/2] 白で塗りつぶしました。")
print(" → パネルが真っ白（またはかなり明るく）変化するか確認してください。")
print("   何も変化しない場合、パネル側の電源・ケーブル・初期化に問題がある可能性があります。")

# --- 黒画面の作成と表示 ---
img_black = Image.new("RGB", (disp.width, disp.height), "black")
disp.set_image(img_black)
disp.show()
print("\n[2/2] 黒で塗りつぶしました。")
print(" → パネルが暗く（または黒く）変化するか確認してください。")
print("   これも変化しない場合、描画回路のハング・電圧不足・コネクタ接触不良の可能性があります。")

print("\n=== パネルテスト終了 ===")
