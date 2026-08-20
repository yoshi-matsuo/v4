#!/bin/bash
# launchdから呼び出される統合ラッパー。
# STOCK ARENAとNEXT投資ワードを順に実行するが、互いの結果には影響しない：
# - STOCK ARENAは従来どおり単独で実行し、その終了コードだけをこのラッパーの終了コードにする。
# - NEXT投資ワードはSTOCK ARENAの後に独立して実行し、失敗してもSTOCK ARENA側の完了済みの
#   更新結果やこのラッパーの終了コードには影響させない（set -eを使わないのはそのため）。
set -uo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

PY="$HERE/.venv_youtube_sync/bin/python"

echo "===== $(date '+%Y-%m-%d %H:%M:%S') STOCK ARENA sync start ====="
"$PY" "$HERE/update_stock_arena_youtube.py"
SA_STATUS=$?
echo "===== STOCK ARENA sync exit code: $SA_STATUS ====="

echo "===== $(date '+%Y-%m-%d %H:%M:%S') NEXT投資ワード sync start ====="
"$PY" "$HERE/update_next_investment_word_youtube.py"
NEXT_STATUS=$?
echo "===== NEXT投資ワード sync exit code: $NEXT_STATUS ====="

exit "$SA_STATUS"
