#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import py_compile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "update_stock_arena_youtube.py"
BACKUP = ROOT / "update_stock_arena_youtube_before_stock_only_fix.py"

if not TARGET.exists():
    raise SystemExit(f"対象ファイルがありません: {TARGET}")

text = TARGET.read_text(encoding="utf-8")

old_func = '''def is_stock_arena_video(v: dict, config: dict) -> bool:
    if v["privacy_status"] != "public":
        return False
    if v["duration_seconds"] < int(config.get("min_duration_seconds", 180)):
        return False

    title = v["title"]
    for kw in config.get("exclude_title_keywords", []):
        if kw and kw.lower() in title.lower():
            return False
    return True
'''

new_func = '''def is_stock_arena_video(v: dict, config: dict, baseline_video_ids: set[str]) -> bool:
    """
    STOCK ARENAの個別企業動画だけを採用する。

    - 初期ベースラインに含まれていた動画はそのまま維持。
    - ベースライン以後の新規動画は、先頭が【企業名】形式の個別企業動画だけ追加。
    - 同じチャンネルのNEXT投資ワード等のテーマ動画は混入させない。
    """
    if v["privacy_status"] != "public":
        return False
    if v["duration_seconds"] < int(config.get("min_duration_seconds", 180)):
        return False

    title = v["title"]

    for kw in config.get("exclude_title_keywords", []):
        if kw and kw.lower() in title.lower():
            return False

    # 初期100本など、すでにSTOCK ARENAとして確定した動画は維持。
    if v["video_id"] in baseline_video_ids:
        return True

    # 新規動画は【企業名】で始まる個別企業動画だけを採用。
    m = re.match(r"^【([^】]+)】", title)
    if not m:
        return False

    bracket = m.group(1).strip()
    generic_labels = {
        "日本株", "米国株", "NEXT投資ワード",
        "今日の日本株速報", "今日の米国株速報",
        "朝イチマーケット情報", "COMPANY ARCHIVE",
        "AI", "半導体", "データセンター", "防衛", "宇宙",
    }
    if bracket in generic_labels:
        return False

    return True
'''

old_baseline = '''    baseline_perf_rows = read_csv_dict(BASELINE_PERF_PATH)
    baseline_perf_by_id = {r.get("動画ID", ""): r for r in baseline_perf_rows}
'''

new_baseline = '''    baseline_perf_rows = read_csv_dict(BASELINE_PERF_PATH)
    baseline_perf_by_id = {r.get("動画ID", ""): r for r in baseline_perf_rows}
    baseline_video_ids = {vid for vid in baseline_perf_by_id if vid}
'''

old_filter = '''    metadata = get_video_metadata(youtube, upload_ids)
    videos = [v for v in metadata if is_stock_arena_video(v, config)]
'''

new_filter = '''    metadata = get_video_metadata(youtube, upload_ids)
    videos = [
        v for v in metadata
        if is_stock_arena_video(v, config, baseline_video_ids)
    ]
'''

if new_func in text:
    print("すでに修正済みです。")
else:
    missing = []
    if old_func not in text:
        missing.append("is_stock_arena_video")
    if old_baseline not in text:
        missing.append("baseline section")
    if old_filter not in text:
        missing.append("video filter")
    if missing:
        raise SystemExit(
            "想定していたコードと一致しないため、安全のため修正を中止しました: "
            + ", ".join(missing)
        )

    shutil.copy2(TARGET, BACKUP)
    text = text.replace(old_func, new_func)
    text = text.replace(old_baseline, new_baseline)
    text = text.replace(old_filter, new_filter)
    TARGET.write_text(text, encoding="utf-8")

    py_compile.compile(str(TARGET), doraise=True)
    print(f"[OK] 修正完了: {TARGET.name}")
    print(f"[OK] バックアップ: {BACKUP.name}")
    print("[OK] 初期ベースラインは維持し、新規追加は【企業名】形式の個別企業動画だけになります。")
