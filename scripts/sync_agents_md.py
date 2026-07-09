#!/usr/bin/env python3
"""
.agents/AGENTS.md 再生成スクリプト（Antigravity CLI互換用）
CLAUDE.md（単一ソース）＋ framework/*.md ＋ .agents/ANTIGRAVITY_SUPPLEMENT.md から生成する。
AGENTS.md を直接編集しないこと（次回生成で上書きされる）。

クロスプラットフォーム対応（Mac/Windows/Linux共通）。bash不要。
使い方: python3 scripts/sync_agents_md.py  （Windowsでは python でも可）
"""
import datetime
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent
OUT = HUB / '.agents' / 'AGENTS.md'


def main():
    parts = []
    parts.append(
        f"<!-- AUTO-GENERATED — CLAUDE.md + framework/*.md + .agents/ANTIGRAVITY_SUPPLEMENT.md "
        f"から scripts/sync_agents_md.py で生成（{datetime.datetime.now().strftime('%Y-%m-%d %H:%M')}）。"
        f"直接編集禁止。 -->\n"
    )

    claude_md = HUB / 'CLAUDE.md'
    if claude_md.exists():
        parts.append(claude_md.read_text(encoding='utf-8'))

    framework_dir = HUB / 'framework'
    if framework_dir.exists():
        for f in sorted(framework_dir.glob('*.md')):
            parts.append('\n---\n')
            parts.append(f.read_text(encoding='utf-8'))

    supplement = HUB / '.agents' / 'ANTIGRAVITY_SUPPLEMENT.md'
    if supplement.exists():
        parts.append(supplement.read_text(encoding='utf-8'))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    content = '\n'.join(parts)
    OUT.write_text(content, encoding='utf-8')
    print(f"generated: {OUT} ({len(content.encode('utf-8'))} bytes)")


if __name__ == '__main__':
    main()
