# ダッシュボード — エージェント活動のリアルタイム可視化（任意モジュール）

ブラウザ（http://localhost:8765）で、司令塔とサブエージェントの活動をリアルタイムに眺められる画面。**Mac / Windows / Linux 共通の作りで動く。**

## 仕組み

```
Claude Code / Antigravity のフック（ツール実行のたびに発火）
   └→ dashboard/log_hook.py が dashboard/logs/events.jsonl に1行追記
        └→ dashboard/server.py（Python製・ポート8765）がtailしてブラウザに配信
             └→ dashboard/index.html が描画
```

- ログは**サブエージェントの識別情報**（`agent_id`：空なら司令塔、`child_agent_id`：起動された子エージェント）を含み、親子の紐付け＝「どの部門が今動いているか」を可視化できる。
- log_hook.py は Claude Code と Antigravity CLI 両方のペイロード形式を吸収する。失敗しても本体の動作を止めない設計。

## セットアップ（Claudeに「ダッシュボードを設定して」と言えば全部やってくれる）

1. **フックの有効化**：`.claude/settings.template.json` の `{{HUB_PATH}}`（このリポジトリの絶対パス）と `{{PYTHON_CMD}}`（`python3` または `python`。Windowsは通常 `python`）を置換し、`.claude/settings.json` として保存する。（Antigravity併用なら `.agents/hooks.template.json` → `.agents/hooks.json` も同様に）
2. **サーバーの自動起動登録**（OSを自動判定して分岐する）：
   ```bash
   python3 dashboard/install_dashboard.py
   ```
   - **macOS**：launchdに登録（ログイン時起動・クラッシュ時自動再起動）
   - **Windows**：スタートアップフォルダにショートカットを配置（管理者権限不要・次回ログインから自動起動）
   - **Linux**：自動起動は未対応。手動起動のコマンドが案内される
3. ブラウザで http://localhost:8765 を開く。

手動で一時的に起動したいだけなら：`python3 dashboard/server.py`（ポート変更は `python3 dashboard/server.py 9000`）。Windowsでは `python3` の代わりに `python` を使う場合がある。

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
