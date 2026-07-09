#!/bin/bash
# ダッシュボードの launchd 自動起動を設定するスクリプト（macOS専用）
# 使い方: bash dashboard/install_dashboard.sh
# → ログイン時に自動でダッシュボードサーバーが立ち上がるようになる（http://localhost:8765）
set -euo pipefail

HUB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
USER_NAME="$(whoami)"
PYTHON_PATH="$(command -v python3)"
LABEL="com.${USER_NAME}.agent-hub.dashboard"
PLIST="$HOME/Library/LaunchAgents/${LABEL}.plist"

if [ -z "$PYTHON_PATH" ]; then
  echo "エラー: python3 が見つかりません。先に Python 3 をインストールしてください。" >&2
  exit 1
fi

mkdir -p "$HUB/dashboard/logs" "$HOME/Library/LaunchAgents"

sed -e "s|{{HUB_PATH}}|$HUB|g" \
    -e "s|{{USER_NAME}}|$USER_NAME|g" \
    -e "s|{{PYTHON_PATH}}|$PYTHON_PATH|g" \
    "$HUB/dashboard/launchd.plist.template" > "$PLIST"

# 既に読み込まれていたら一度外してから読み込む（再インストール対応）
launchctl unload "$PLIST" 2>/dev/null || true
launchctl load "$PLIST"

echo "✅ ダッシュボードを自動起動に登録しました: $LABEL"
echo "   ブラウザで http://localhost:8765 を開いてください。"
echo "   解除したいとき: launchctl unload \"$PLIST\" && rm \"$PLIST\""
