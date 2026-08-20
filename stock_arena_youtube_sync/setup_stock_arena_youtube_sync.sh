#!/bin/bash
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
cd "$HERE"

if [ ! -f "client_secret.json" ]; then
  echo "client_secret.json がありません。"
  echo "README_stock_arena_youtube_sync.txt の手順でGoogle Cloudから取得し、このフォルダに置いてください。"
  exit 1
fi

if command -v python3.12 >/dev/null 2>&1; then
  PY=python3.12
else
  PY=python3
fi

VENV="$HERE/.venv_youtube_sync"

if [ ! -d "$VENV" ]; then
  "$PY" -m venv "$VENV"
fi

"$VENV/bin/python" -m pip install --upgrade pip
"$VENV/bin/pip" install -r "$HERE/requirements_stock_arena_youtube_sync.txt"

echo
echo "初回認証とデータ更新を開始します。Googleの認証画面がブラウザで開きます。"
"$VENV/bin/python" "$HERE/update_stock_arena_youtube.py"

chmod +x "$HERE/run_youtube_sync_all.sh"

PLIST="$HOME/Library/LaunchAgents/com.stockarena.youtube-sync.plist"
mkdir -p "$HOME/Library/LaunchAgents"

# STOCK ARENAとNEXT投資ワードを順に実行するラッパー経由で起動する。
# NEXT側が失敗してもSTOCK ARENA側の更新結果には影響しない
# （run_youtube_sync_all.sh 内でSTOCK ARENAの終了コードのみを採用）。
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>com.stockarena.youtube-sync</string>

  <key>ProgramArguments</key>
  <array>
    <string>$HERE/run_youtube_sync_all.sh</string>
  </array>

  <key>WorkingDirectory</key>
  <string>$HERE</string>

  <key>StartInterval</key>
  <integer>21600</integer>

  <key>RunAtLoad</key>
  <true/>

  <key>StandardOutPath</key>
  <string>$HERE/youtube_sync.log</string>

  <key>StandardErrorPath</key>
  <string>$HERE/youtube_sync_error.log</string>
</dict>
</plist>
EOF

launchctl bootout "gui/$(id -u)" "$PLIST" >/dev/null 2>&1 || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl enable "gui/$(id -u)/com.stockarena.youtube-sync"

echo
echo "設定完了。以後は約6時間ごとに自動更新します。"
echo "出力:"
echo "  $HERE/stock_arena_history.csv"
echo "  $HERE/stock_arena_youtube_performance.csv"
