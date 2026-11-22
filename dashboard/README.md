# ダッシュボード — エージェント活動のリアルタイム可視化（任意モジュール）

ブラウザ（http://localhost:8765）で、司令塔とサブエージェントの活動をリアルタイムに眺められる画面。**Mac / Windows / Linux 共通の作りで動く。**

## 仕組み

```
Claude Code のフック（ツール実行のたびに発火）
   └→ dashboard/log_hook.py が dashboard/logs/events.jsonl に1行追記
        └→ dashboard/server.py（Python製・ポート8765）がtailしてブラウザに配信
             └→ dashboard/index.html が描画
```

- ログは**サブエージェントの識別情報**（`agent_id`：空なら司令塔、`child_agent_id`：起動された子エージェント）を含み、親子の紐付け＝「どの部門が今動いているか」を可視化できる。
- log_hook.py は失敗しても本体の動作を止めない設計。

## セットアップ（Claudeに「ダッシュボードを設定して」と言えば全部やってくれる）

1. **フックの有効化**：`.claude/settings.template.json` の `{{HUB_PATH}}`（このリポジトリの絶対パス）と `{{PYTHON_CMD}}`（`python3` または `python`。Windowsは通常 `python`）を置換し、`.claude/settings.json` として保存する。
2. **サーバーの自動起動登録**（OSを自動判定して分岐する）：
   ```bash
   python3 dashboard/install_dashboard.py
   ```
   - **macOS**：launchdに登録（ログイン時起動・クラッシュ時自動再起動）
   - **Windows**：スタートアップフォルダにショートカットを配置（管理者権限不要・次回ログインから自動起動）
   - **Linux**：自動起動は未対応。手動起動のコマンドが案内される
3. ブラウザで http://localhost:8765 を開く。

手動で一時的に起動したいだけなら：`python3 dashboard/server.py`（ポート変更は `python3 dashboard/server.py 9000`）。Windowsでは `python3` の代わりに `python` を使う場合がある。

## 日次報告（Claude manager）の表示

日次報告を有効にしていると、Monitor のエージェント一覧の下に「Claude manager」の枠が出て、今日の報告が緊急度ごとに並ぶ。まだ1件も報告が無いあいだは枠ごと出ない。仕組みと設定は `framework/03_日次報告.md`。

- 報告の右のチェックを付けると、その件は「解決済み」として隠れる。印を付けた件は、新しい事実が出ない限り翌日以降の報告にも出ない。枠の見出しの「解決済み◯件を表示」で戻せる。
- 会話ログからの学習を使っていると、いちばん下に「学習」の段が出る（覚えたこと・書き直したこと・自動化の候補）。番号は取り消すときに使う（`framework/06_会話ログからの学習.md`）。

部門カードの名前は `hub.config.json` の `daily_report.departments` の表示名、無ければ各部門の最初のエージェントの見出しから取る。色は部門番号で決まる。

## Galaxy ビュー（http://localhost:8765/galaxy）

ダッシュボード右上の「🌌 Galaxy」から開ける、Obsidianのグラフビュー風の3D可視化。司令塔・エージェント・各CLAUDE.mdの指示セクション・`shared/`や`framework/`配下の全ファイル・Claude Codeの記憶（`[[wikilink]]`込み）を、脳の形に力場で閉じ込めた発光体の集合として描画する。

- **セットアップ前でも動く**：`framework/`・`setup/`・`integrations/`・`examples/`はリポジトリに最初から存在するため、部門を作る前でもフレームワークの骨格が星図として見える。セットアップ後は `agents/`・`shared/`・記憶が加わってどんどん密度が増す。
- 操作：ドラッグ＝回転／スクロール＝ズーム／ホバー＝接続表示／ダブルクリック＝リセット。左下の「FORCES」で反発力・リンク距離・脳の形のON/OFFを調整できる。
- 記憶ノードは `~/.claude/projects/` 配下から、このリポジトリのパスに対応するフォルダを自動推定して読む（ハードコードなし）。見つからない場合は記憶ノード無しで残りが描画される（エラーにはならない）。

## アンインストール

- **macOS**：
  ```bash
  launchctl unload ~/Library/LaunchAgents/com.$(whoami).agent-hub.dashboard.plist
  rm ~/Library/LaunchAgents/com.$(whoami).agent-hub.dashboard.plist
  ```
- **Windows**：スタートアップフォルダ（`install_dashboard.py`実行時に表示されたパス。通常 `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup`）内の `agent-hub-dashboard.bat` を削除する。

## 注意

- ログ（`dashboard/logs/events.jsonl`）にはツール入力の先頭400字が記録される。**個人データの断片が含まれる**ので、このファイルを共有しないこと（.gitignore済み）。
- ローカル専用サーバー。外部公開しない前提の作りなので、ポートをインターネットに開放しないこと。
