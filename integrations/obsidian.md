# 連携ガイド：Obsidian（スマホ同期メモ）

## 何ができるようになるか

- iPhoneのObsidianアプリで書いたタスク・メモを、PCのエージェントが読み取って管理に使える。
- 逆にエージェントが更新したタスクリストがスマホに同期される。
- 「スマホで走り書き → エージェントが正式な記録に整形」という**受信箱パターン**（`framework/05` パターン3）が組める。

## 前提

- Obsidianアプリ（PC・スマホ両方）は導入者自身がインストールする（無料）。
- スマホと同期するには **iCloud同期**（iPhone/Macなら無料）か Obsidian Sync（有料）を使う。以下はiCloud前提。

## 手順

1. **スマホ側**：Obsidianアプリで新規Vault作成時に「iCloudに保存」を選ぶ。
2. **Mac側**：同じApple IDでiCloud Driveが有効なら、Vaultは自動で以下に現れる：
   ```
   ~/Library/Mobile Documents/iCloud~md~obsidian/Documents/（Vault名）/
   ```
   Claudeが `ls` で実際のパスを特定する（導入者はVault名を伝えるだけでよい）。
3. **`hub.config.json` の `paths.obsidian_vault` にフルパスを記録**し、`integrations.obsidian` を `true` にする。
4. タスク管理系エージェントの CLAUDE.md のデータソース表に、Vault内の対象ファイル（例：`todo.md`）をフルパスで記載する。

## 運用ルール（重要）

- **オーナーが直接編集するファイル**なので、エージェントは書き方を勝手に整形しない。
- 目標リスト等のオーナー所有ファイルは、エージェントは**進捗確認のみ**（書き込みは本人が明示したときだけ）。
- 受信箱ファイル（quick-log）を作る場合、エージェントは取り込み済み行に ✅ を付けるだけにする。

## つまずきやすい点

- Mac側にVaultが現れない → Mac の システム設定 > Apple ID > iCloud > iCloud Drive がオンか確認。スマホ側でVaultに1ファイル作ると同期が始まることがある。
- パスに空白・日本語が含まれていても問題ないが、エージェントのCLAUDE.mdには**フルパスを正確に**書くこと（Claudeに任せれば確実）。
- iCloud同期はリアルタイムではない（数秒〜数分の遅延）。「さっきスマホで書いたのに見えない」ときは少し待つ。
