#!/bin/bash
# .agents/AGENTS.md 再生成スクリプト（Antigravity CLI互換用）
# CLAUDE.md（単一ソース）＋ .agents/ANTIGRAVITY_SUPPLEMENT.md（読み替えルール）から生成する。
# AGENTS.md を直接編集しないこと（次回生成で上書きされる）。
set -euo pipefail

# スクリプト自身の場所からハブのルートを導出（どこにcloneしても動く）
HUB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OUT="$HUB/.agents/AGENTS.md"

{
  echo "<!-- AUTO-GENERATED — CLAUDE.md + .agents/ANTIGRAVITY_SUPPLEMENT.md から scripts/sync_agents_md.sh で生成（$(date '+%Y-%m-%d %H:%M')）。直接編集禁止。 -->"
  echo ""
  cat "$HUB/CLAUDE.md"
  # framework/ 配下の司令塔ルールも単一ファイルに連結する（Antigravityが確実に読めるように）
  for f in "$HUB"/framework/*.md; do
    [ -f "$f" ] && { echo ""; echo "---"; echo ""; cat "$f"; }
  done
  cat "$HUB/.agents/ANTIGRAVITY_SUPPLEMENT.md"
} > "$OUT.tmp" && mv "$OUT.tmp" "$OUT"

echo "generated: $OUT ($(wc -c < "$OUT") bytes)"
