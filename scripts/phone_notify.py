#!/usr/bin/env python3
"""日次報告をスマホのLINEへ届ける（LINE公式アカウントの Messaging API）。全部の報告を1通にまとめる。

  python3 scripts/phone_notify.py setup    # チャネルアクセストークンを登録して、試しに1通送る（最初の1回だけ）
  python3 scripts/phone_notify.py test     # 試しに1通送る
  python3 scripts/phone_notify.py send     # 最新の日次報告を送り直す

送り方は「友だち全員へ配信」。この公式アカウントの友だちは自分だけにしておく（ほかの人を足すと、その人にも届く）。
1回の配信＝1通と数える。毎朝1通なので月30通ほど（無料で送れる通数はLINE公式アカウントのプランで決まる）。
トークンは dashboard/notify.json に置く（gitには載せない）。止めるときは notify.json を消す。
claude_manager.py が毎朝の報告を書いたあとに send_report() を呼ぶ。設定していなければ何もしない。
準備の手順は integrations/line-notify.md。Windowsでは python3 の代わりに python。
"""
import getpass
import json
import os
import pathlib
import sys
import urllib.error
import urllib.request

HUB = pathlib.Path(__file__).resolve().parent.parent
CONF = HUB / "dashboard" / "notify.json"
API = "https://api.line.me/v2/bot/message/broadcast"
MARK = {"red": "🔴", "yellow": "🟡", "green": "🟢"}
PER_SEND = 5


def config():
    try:
        c = json.loads(CONF.read_text(encoding="utf-8"))
        return c if c.get("line_token") else None
    except (OSError, ValueError):
        return None


def post(conf, texts):
    """texts を吹き出しにして、5つずつ配信する"""
    for i in range(0, len(texts), PER_SEND):
        body = json.dumps({"messages": [{"type": "text", "text": t[:4900]} for t in texts[i:i + PER_SEND]]},
                          ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(API, data=body, headers={
            "Content-Type": "application/json", "Authorization": "Bearer " + conf["line_token"]})
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                r.read()
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"LINEが受け付けなかった（{e.code}）: {e.read().decode()[:200]}") from None


def send_report(report, labels):
    """全部の報告を1通にまとめて送る（緊急度の高い順）。載せた報告の数を返す"""
    conf = config()
    if not conf:
        return 0
    parts = []
    for it in report.get("items", []):
        names = "・".join(labels.get(n, n) for n in it.get("depts", []))
        parts.append(f"{MARK.get(it.get('level'), '')}{names}｜{it['title']}\n{it.get('body', '')}".strip())
    for f in report.get("failed", []):
        parts.append(f"⚠️{f['label']}｜報告を受け取れず\n{f.get('reason', '')}".strip())
    if not parts:
        return 0
    m, d = report.get("date", "")[5:7].lstrip("0"), report.get("date", "")[8:10].lstrip("0")
    head = f"【日次報告 {m}/{d}】{len(parts)}件"
    if report.get("hitokoto"):
        head += f"\n今日の一手：{report['hitokoto']}"
    post(conf, [head + "\n\n" + "\n\n".join(parts)])
    return len(parts)


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "setup":
        token = getpass.getpass("チャネルアクセストークン（長期）を貼り付けてEnter（画面には出ません）: ").strip()
        if not token:
            print("何も入力されなかった")
            return 1
        conf = {"line_token": token}
        post(conf, ["agent-hub の通知のテストです。届いていれば設定は完了です。"])
        CONF.write_text(json.dumps(conf), encoding="utf-8")
        try:
            os.chmod(CONF, 0o600)
        except OSError:
            pass
        print("登録して、テストを1通送った。LINEに届いているか見る")
        return 0
    conf = config()
    if not conf:
        print("未設定（scripts/phone_notify.py setup を先に）")
        return 1
    if cmd == "test":
        post(conf, ["agent-hub の通知のテストです。"])
        print("送った")
        return 0
    if cmd == "send":
        sys.path.insert(0, str(HUB / "scripts"))
        import claude_manager
        f = claude_manager.latest_file()
        if not f:
            print("報告がまだ無い")
            return 1
        n = send_report(json.loads(f.read_text(encoding="utf-8")),
                        {d["num"]: d["label"] for d in claude_manager.DEPTS})
        print(f"{n}件を送った")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    sys.exit(main())
