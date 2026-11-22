# LINE通知 — 日次報告をスマホに届ける（任意）

毎朝の日次報告を、LINEに1通で届ける。ダッシュボードを開かなくても、朝スマホを見れば読める。

日次報告（`framework/03_日次報告.md`）を使っていることが前提。

## 仕組み

自分専用のLINE公式アカウントを1つ作り、そこから自分あてに配信する。`scripts/phone_notify.py` が LINE の Messaging API を呼ぶ。

- 送るのは1日1通（全部の報告をまとめて1通）。報告が1件も無い日は送らない。
- 無料で送れる通数は、LINE公式アカウントのプランで決まる。申し込む前に、今の料金表を自分で確かめる。
- **報告の中身（部門名・見出し・本文）がLINEのサーバーを通る。** それでよいかを決めてから始める。

## 準備（オーナーがブラウザで行う）

1. LINE公式アカウントを作る（LINE Official Account Manager）。名前は自分が分かればよい。
2. 設定で Messaging API を有効にする。
3. LINE Developers のコンソールで、そのチャネルの**チャネルアクセストークン（長期）**を発行する。
4. スマホのLINEで、その公式アカウントを友だちに追加する。**友だちは自分だけにする**（送り方が「友だち全員へ配信」なので、ほかの人を足すとその人にも届く）。

## 登録（オーナーがターミナルで行う）

```bash
python3 scripts/phone_notify.py setup
```

トークンを貼り付けると、試しに1通届く。トークンは `dashboard/notify.json` に置かれる（gitには載らない）。**トークンは司令塔に渡さない。** チャットに貼らず、上のコマンドに自分で入力する。

登録できたら `hub.config.json` の `integrations.line_notify` を `true` にする。

## 使う

- 試しに送る → `python3 scripts/phone_notify.py test`
- 最新の報告を送り直す → `python3 scripts/phone_notify.py send`
- 止める → `dashboard/notify.json` を消す
