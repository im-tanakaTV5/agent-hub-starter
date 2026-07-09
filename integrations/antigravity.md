# 連携ガイド：Antigravity CLI 互換（Claude Code以外でも動かす）

## 何ができるようになるか

- この司令塔一式を Google Antigravity CLI（Gemini）でも同じ精度で動かせる。
- 指示書は **CLAUDE.md＋framework/＋my-hub/ が単一ソース**のまま、Antigravity用の `AGENTS.md` を自動生成する方式なので、二重管理にならない。

## 仕組み

```
CLAUDE.md ＋ framework/*.md ＋ .agents/ANTIGRAVITY_SUPPLEMENT.md
        │
        └─ scripts/sync_agents_md.py ──→ .agents/AGENTS.md（自動生成・直接編集禁止）
```

- ルートの `AGENTS.md` は「`.agents/AGENTS.md` を読め」というポインタ（Antigravityに確実に読ませるため）。
- `.agents/ANTIGRAVITY_SUPPLEMENT.md` に読み替えルール（`Agent`→`start_subagent`、モデルティア対応、Chrome操作の代替）が書いてある。ハーネス固有の差分はこのファイルにだけ書く。
- 生成スクリプトは純粋なPython製で **Mac / Windows / Linux 共通**（bash不要）。

## 手順

1. 生成スクリプトを一度実行する（Claudeが実行。どのOSでも同じコマンド）：
   ```bash
   python3 scripts/sync_agents_md.py
   ```
   ※ Windowsで `python3` が見つからない場合は `python` を試す。
2. Claude Code側のフックを有効にしていれば（`.claude/settings.json`）、以後 CLAUDE.md や framework/ を編集するたびに自動で再生成される。
3. Antigravity側のフック（ダッシュボード連携）を使う場合は、`.agents/hooks.template.json` の `{{HUB_PATH}}` と `{{PYTHON_CMD}}` をこのリポジトリの絶対パスと実際のPythonコマンドに置換して `.agents/hooks.json` として保存する（Claudeが実施）。
4. `hub.config.json` の `integrations.antigravity` を `true` にする。

## 運用ルール（重要）

- **`.agents/AGENTS.md` を直接編集しない**（次回生成で消える）。指示を変えるときは CLAUDE.md / framework/ / my-hub/ を編集する。
- **Antigravityは必ずリポジトリのルートから起動する**（サブフォルダから起動すると指示書が読まれない）。
- ダッシュボードのログフック（`dashboard/log_hook.py`）は Claude Code / Antigravity 両方のペイロード形式を吸収する設計になっているので、両ハーネスの活動が同じダッシュボードに載る。
