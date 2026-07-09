#!/usr/bin/env python3
"""
PostToolUse フック（Claude Code用）:
CLAUDE.md または framework/ 配下が Edit/Write されたら .agents/AGENTS.md を自動再生成する。
ログ専用フックと同じく、失敗しても本体の動作を絶対に止めない（常に正常終了する）。

クロスプラットフォーム対応（Mac/Windows/Linux共通）。bash不要。
"""
import json
import subprocess
import sys
from pathlib import Path

HUB = Path(__file__).resolve().parent.parent


def main():
    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    haystack = json.dumps(data, ensure_ascii=False)
    if 'CLAUDE.md' in haystack or 'framework' in haystack:
        try:
            subprocess.run(
                [sys.executable, str(HUB / 'scripts' / 'sync_agents_md.py')],
                capture_output=True, timeout=10
            )
        except Exception:
            pass  # フックは本体の動作を止めない

    sys.exit(0)


if __name__ == '__main__':
    main()
