#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import py_compile
from datetime import datetime
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "update_stock_arena_youtube.py"
BACKUP = ROOT / "update_stock_arena_youtube_before_missing_baseline_fallback.py"

if not TARGET.exists():
    raise SystemExit(f"対象ファイルがありません: {TARGET}")

text = TARGET.read_text(encoding="utf-8")

old = '''    metadata = get_video_metadata(youtube, lookup_ids)
    videos = [
        v for v in metadata
        if is_stock_arena_video(v, config, baseline_video_ids)
    ]
'''

new = '''    metadata = get_video_metadata(youtube, lookup_ids)

    # YouTube Data API側で既知の動画IDがmetadataに返らない場合でも、
    # 初期ベースラインにあるSTOCK ARENA動画は落とさない。
    # baselineの公開日・タイトル・長さを使って最小metadataを補完し、
    # Analyticsは動画IDで引き続き更新する。
    returned_ids = {v["video_id"] for v in metadata}
    missing_baseline_ids = baseline_video_ids - returned_ids

    if missing_baseline_ids:
        print(f"[WARN] Data API metadata未返却の既知動画: {len(missing_baseline_ids)}本")
        for vid in sorted(missing_baseline_ids):
            row = baseline_perf_by_id.get(vid, {})
            pub_str = row.get("公開日", "")
            title = row.get("動画タイトル", "")
            duration = as_int(row.get("長さ秒"))

            if not pub_str or not title:
                print(f"[WARN] baseline補完不可: {vid}")
                continue

            pub_jst = datetime.fromisoformat(pub_str).replace(tzinfo=JST)
            metadata.append({
                "video_id": vid,
                "title": title,
                "published_at": pub_jst.astimezone(timezone.utc),
                "published_date_jst": pub_jst.date(),
                "published_date_pt": pub_jst.astimezone(PT).date(),
                "duration_seconds": duration,
                # baseline収録済み＝STOCK ARENA既知動画として保持。
                "privacy_status": "public",
                "public_view_count": as_int(row.get("視聴回数")),
            })
            print(f"[INFO] baselineから補完: {vid} | {title}")

    videos = [
        v for v in metadata
        if is_stock_arena_video(v, config, baseline_video_ids)
    ]
'''

if new in text:
    print("すでに修正済みです。")
else:
    if old not in text:
        raise SystemExit("想定コードと一致しないため、安全のため修正を中止しました。")

    shutil.copy2(TARGET, BACKUP)
    text = text.replace(old, new)
    TARGET.write_text(text, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print(f"[OK] 修正完了: {TARGET.name}")
    print(f"[OK] バックアップ: {BACKUP.name}")
    print("[OK] Data APIが返さない既知動画でも、baselineから補完して履歴・Analytics更新対象に残します。")
