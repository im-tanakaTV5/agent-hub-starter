# 連携ガイド：Obsidian（スマホ同期メモ）

## 何ができるようになるか

- スマホのObsidianアプリで書いたタスク・メモを、PCのエージェントが読み取って管理に使える。
- 逆にエージェントが更新したタスクリストがスマホに同期される。
- 「スマホで走り書き → エージェントが正式な記録に整形」という**受信箱パターン**（`framework/05` パターン3）が組める。

## 前提

- Obsidianアプリ（PC・スマホ両方）は導入者自身がインストールする（無料）。
- スマホと同期するには何らかのクラウド同期が必要。**OSによって使う仕組みが変わる**（下記）。

## 同期方法の選び方（OS別）

| PC環境 | 推奨の同期方法 | Vaultのローカルパス（目安） |
|--------|--------------|---------------------------|
| **Mac + iPhone** | iCloud Drive（無料・標準搭載） | `~/Library/Mobile Documents/iCloud~md~obsidian/Documents/（Vault名）/` |
| **Windows + iPhone** | iCloud for Windows（無料アプリをインストール） | `C:\Users\（ユーザー名）\iCloudDrive\iCloud~md~obsidian\Documents\（Vault名）\` |
| **Windows + Android** | OneDriveまたはGoogleドライブ同期用アプリ | `C:\Users\（ユーザー名）\OneDrive\（Vault名）\` など、選んだサービスに準じる |
| **どのOSでも（有料）** | Obsidian公式の「Obsidian Sync」 | ローカルはどこでもよい（アプリ内で選んだ場所） |

Claudeが実際のパスを `dir`（Windows）や `ls`（Mac）で特定するので、導入者はVault名とどの同期方法を使っているかを伝えるだけでよい。

## 手順

1. **スマホ側**：Obsidianアプリで新規Vault作成時に、選んだ同期方法（iCloud / OneDrive / Obsidian Sync）でクラウドに保存する設定にする。
2. **PC側**：
   - Windowsで「iCloud for Windows」を使う場合は、Microsoft StoreまたはApple公式サイトからインストールし、同じApple IDでサインインする。
   - PC側のObsidianアプリで同じVaultを開く（クラウドフォルダ内のVaultフォルダを指定する）。
3. Claudeが実際のフルパスを特定し、**`hub.config.json` の `paths.obsidian_vault` に記録**し、`integrations.obsidian` を `true` にする。
4. タスク管理系エージェントの CLAUDE.md のデータソース表に、Vault内の対象ファイル（例：`todo.md`）をフルパスで記載する。

## 運用ルール（重要）

- **オーナーが直接編集するファイル**なので、エージェントは書き方を勝手に整形しない。
- 目標リスト等のオーナー所有ファイルは、エージェントは**進捗確認のみ**（書き込みは本人が明示したときだけ）。
- 受信箱ファイル（quick-log）を作る場合、エージェントは取り込み済み行に ✅ を付けるだけにする。

## つまずきやすい点

- **Windows**：iCloudDriveフォルダが見当たらない → 「iCloud for Windows」アプリでiCloud Driveのチェックボックスが有効か確認。エクスプローラーの左メニューに「iCloudDrive」が出ているか見る。
- **Mac**：Vaultが現れない → システム設定 > Apple ID > iCloud > iCloud Drive がオンか確認。
- どちらのOSでも、スマホ側でVaultに1ファイル作ると同期が始まることがある。
- クラウド同期はリアルタイムではない（数秒〜数分の遅延）。「さっきスマホで書いたのに見えない」ときは少し待つ。
- パスに空白・日本語が含まれていても問題ないが、エージェントのCLAUDE.mdには**フルパスを正確に**書くこと（Claudeに任せれば確実）。
