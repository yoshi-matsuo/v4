#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import shutil
import py_compile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "update_stock_arena_youtube.py"
BACKUP = ROOT / "update_stock_arena_youtube_before_baseline_union_fix.py"

if not TARGET.exists():
    raise SystemExit(f"対象ファイルがありません: {TARGET}")

text = TARGET.read_text(encoding="utf-8")

old = '''    upload_ids = list_upload_ids(youtube, ch["uploads_playlist"])
    metadata = get_video_metadata(youtube, upload_ids)
    videos = [
        v for v in metadata
        if is_stock_arena_video(v, config, baseline_video_ids)
    ]
'''

new = '''    upload_ids = list_upload_ids(youtube, ch["uploads_playlist"])

    # uploadsプレイリストだけに依存しない。
    # 初期ベースラインに含まれる既知のSTOCK ARENA動画IDも必ず直接照会する。
    # これにより、公開中なのにuploads一覧から何らかの理由で取りこぼした動画も拾える。
    lookup_ids = list(dict.fromkeys(upload_ids + list(baseline_video_ids)))

    metadata = get_video_metadata(youtube, lookup_ids)
    videos = [
        v for v in metadata
        if is_stock_arena_video(v, config, baseline_video_ids)
    ]
'''

if new in text:
    print("すでに修正済みです。")
else:
    if old not in text:
        raise SystemExit(
            "想定していたコードと一致しないため、安全のため修正を中止しました。"
        )

    shutil.copy2(TARGET, BACKUP)
    text = text.replace(old, new)
    TARGET.write_text(text, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

    print(f"[OK] 修正完了: {TARGET.name}")
    print(f"[OK] バックアップ: {BACKUP.name}")
    print("[OK] uploads一覧 + 初期ベースライン動画IDの和集合をYouTube APIへ直接照会するよう変更しました。")
    print("[OK] 東京エレクトロンデバイス、楽天銀行のような公開動画の取りこぼしも再取得対象になります。")
