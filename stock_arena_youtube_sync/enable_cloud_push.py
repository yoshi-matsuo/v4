#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from pathlib import Path
import json, shutil, py_compile

ROOT = Path(__file__).resolve().parent
TARGET = ROOT / "update_stock_arena_youtube.py"
CONFIG = ROOT / "stock_arena_sync_config.json"
BACKUP = ROOT / "update_stock_arena_youtube_before_cloud_push.py"

text = TARGET.read_text(encoding="utf-8")

if "def push_candidate_scout_data" not in text:
    marker = "def main():\n"
    insert = '''def push_candidate_scout_data(config: dict) -> None:
    api_url = (config.get("cloud_api_url") or "").rstrip("/")
    write_key = config.get("cloud_write_key") or ""
    if not api_url or not write_key:
        return

    payload = {
        "history": read_csv_dict(HISTORY_PATH),
        "performance": read_csv_dict(PERF_PATH),
        "source_updated_at": datetime.now(JST).isoformat(),
    }

    try:
        resp = requests.post(
            f"{api_url}/admin/sync",
            headers={"Authorization": f"Bearer {write_key}"},
            json=payload,
            timeout=60,
        )
        resp.raise_for_status()
        result = resp.json()
        print(f"[OK] Candidate Scout Cloud同期: history={result.get('history_count')} / performance={result.get('performance_count')}")
    except Exception as e:
        print(f"[WARN] Candidate Scout Cloud同期失敗: {e}")


'''
    old_call = '''    write_csv(HISTORY_PATH, history_rows, history_fields)
    write_csv(PERF_PATH, perf_rows, perf_fields)

    print()
'''
    new_call = '''    write_csv(HISTORY_PATH, history_rows, history_fields)
    write_csv(PERF_PATH, perf_rows, perf_fields)
    push_candidate_scout_data(config)

    print()
'''
    if marker not in text or old_call not in text:
        raise SystemExit("想定コードと一致しないため、安全のため中止しました。")
    shutil.copy2(TARGET, BACKUP)
    text = text.replace(marker, insert + marker, 1)
    text = text.replace(old_call, new_call, 1)
    TARGET.write_text(text, encoding="utf-8")
    py_compile.compile(str(TARGET), doraise=True)

config = json.loads(CONFIG.read_text(encoding="utf-8"))
config.setdefault("cloud_api_url", "")
config.setdefault("cloud_write_key", "")
CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

print("[OK] Mac側UpdaterへCloud自動同期機能を追加しました。")
print("[OK] URL/キー未設定の間は従来どおりローカル更新だけ行います。")
