#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / "stock_arena_sync_config.json"
CREDS = ROOT / "candidate_api" / "cloud_api_credentials.txt"

if not CONFIG.exists():
    raise SystemExit(f"設定ファイルがありません: {CONFIG}")

if not CREDS.exists():
    raise SystemExit(f"認証情報ファイルがありません: {CREDS}")

values = {}
for line in CREDS.read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if not line or "=" not in line:
        continue
    key, value = line.split("=", 1)
    values[key.strip()] = value.strip()

api_url = values.get("CLOUD_API_URL", "")
write_key = values.get("WRITE_API_KEY", "")

if not api_url or not write_key:
    raise SystemExit(
        "cloud_api_credentials.txt に CLOUD_API_URL または WRITE_API_KEY がありません。"
    )

config = json.loads(CONFIG.read_text(encoding="utf-8"))
config["cloud_api_url"] = api_url.rstrip("/")
config["cloud_write_key"] = write_key

CONFIG.write_text(
    json.dumps(config, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print("[OK] Cloud API URLを設定しました。")
print("[OK] WRITE_API_KEYを設定しました。")
print("[OK] stock_arena_sync_config.json を更新しました。")
print("[OK] 次回のYouTube自動更新からCloud同期も同時に行われます。")
