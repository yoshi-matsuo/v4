#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import py_compile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "update_stock_arena_youtube.py"
BACKUP = ROOT / "update_stock_arena_youtube_before_cloud_sync_fix.py"

if not TARGET.exists():
    raise SystemExit(f"対象ファイルがありません: {TARGET}")

text = TARGET.read_text(encoding="utf-8")
original = text

# 1) requests import を保証
if "\nimport requests\n" not in text:
    # import群の安全な位置に追加
    marker = "import sys\n"
    if marker not in text:
        raise SystemExit("import位置を特定できないため、安全のため中止しました。")
    text = text.replace(marker, marker + "import requests\n", 1)

# 2) Cloud送信関数が存在することを確認
if "def push_candidate_scout_data" not in text:
    raise SystemExit(
        "push_candidate_scout_data が見つかりません。"
        "enable_cloud_push.py の反映状態が想定と異なります。"
    )

# 3) CSV書込後にCloud同期呼び出しがあることを保証
call = "    push_candidate_scout_data(config)\n"
if call not in text:
    marker = "    write_csv(PERF_PATH, perf_rows, perf_fields)\n"
    if marker not in text:
        raise SystemExit("Cloud同期呼び出し位置を特定できないため、安全のため中止しました。")
    text = text.replace(marker, marker + call, 1)

if text != original:
    shutil.copy2(TARGET, BACKUP)
    TARGET.write_text(text, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    print(f"[OK] 修正完了: {TARGET.name}")
    print(f"[OK] バックアップ: {BACKUP.name}")
else:
    print("[OK] 必要なコードはすでに入っています。")

print("[OK] requests import: 確認済み")
print("[OK] Cloud同期関数: 確認済み")
print("[OK] CSV更新後のCloud同期呼び出し: 確認済み")
