#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import py_compile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "update_stock_arena_youtube.py"
BACKUP = ROOT / "update_stock_arena_youtube_before_video_id_normalize.py"

if not TARGET.exists():
    raise SystemExit(f"対象ファイルがありません: {TARGET}")

text = TARGET.read_text(encoding="utf-8")

repls = [
    (
'''def read_csv_dict(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))
''',
'''def read_csv_dict(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    # YouTube video IDの前後空白を常に除去して同一動画の重複判定を安定させる。
    for row in rows:
        if "動画ID" in row and row["動画ID"] is not None:
            row["動画ID"] = row["動画ID"].strip()
        if "video_id" in row and row["video_id"] is not None:
            row["video_id"] = row["video_id"].strip()
    return rows
'''
    ),
    (
'''            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.append(vid)
''',
'''            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                vid = vid.strip()
                if vid:
                    ids.append(vid)
'''
    ),
    (
'''                "video_id": item["id"],
''',
'''                "video_id": item["id"].strip(),
'''
    ),
    (
'''    baseline_perf_rows = read_csv_dict(BASELINE_PERF_PATH)
    baseline_perf_by_id = {r.get("動画ID", ""): r for r in baseline_perf_rows}
    baseline_video_ids = {vid for vid in baseline_perf_by_id if vid}
''',
'''    baseline_perf_rows = read_csv_dict(BASELINE_PERF_PATH)
    baseline_perf_by_id = {
        (r.get("動画ID", "") or "").strip(): r
        for r in baseline_perf_rows
        if (r.get("動画ID", "") or "").strip()
    }
    baseline_video_ids = set(baseline_perf_by_id)
'''
    ),
    (
'''    old_history = {r.get("動画ID", ""): r for r in read_csv_dict(HISTORY_PATH)}
''',
'''    old_history = {
        (r.get("動画ID", "") or "").strip(): r
        for r in read_csv_dict(HISTORY_PATH)
        if (r.get("動画ID", "") or "").strip()
    }
'''
    ),
]

changed = 0
for old, new in repls:
    if new in text:
        continue
    if old not in text:
        raise SystemExit("想定コードと一致しないため、安全のため修正を中止しました。")
    text = text.replace(old, new)
    changed += 1

if changed == 0:
    print("すでに修正済みです。")
else:
    shutil.copy2(TARGET, BACKUP)
    TARGET.write_text(text, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)
    print(f"[OK] 修正完了: {TARGET.name}")
    print(f"[OK] バックアップ: {BACKUP.name}")
    print("[OK] 動画IDをCSV読込・uploads取得・Data API取得・baseline/履歴比較の全箇所で正規化しました。")
    print("[OK] 前後空白による同一動画の二重計上を防止します。")
