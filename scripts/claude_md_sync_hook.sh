#!/bin/bash
# PostToolUse フック（Claude Code用）:
# CLAUDE.md または framework/ 配下が Edit/Write されたら .agents/AGENTS.md を自動再生成する。
# ログ専用フックと同じく、失敗しても本体の動作を絶対に止めない（常に exit 0）。
HUB="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
input=$(cat 2>/dev/null || true)
if printf '%s' "$input" | grep -q -E 'CLAUDE\.md|framework/'; then
  bash "$HUB/scripts/sync_agents_md.sh" >/dev/null 2>&1 || true
fi
exit 0
