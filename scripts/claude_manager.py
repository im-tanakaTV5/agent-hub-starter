#!/usr/bin/env python3
"""Claude manager。毎朝、全部門に日次報告を出させて、ダッシュボードに短く載せる。

  python3 scripts/claude_manager.py run            # 今日の分がまだ無ければ集める（自動起動が毎朝呼ぶ）
  python3 scripts/claude_manager.py run --force    # 今日の分があっても集め直す
  python3 scripts/claude_manager.py run --only 01,08
  python3 scripts/claude_manager.py show           # 最新の報告を読む

Windowsでは python3 の代わりに python。
部門ごとに claude -p を1本ずつ立てる（読むだけ・Web調査なし）。
報告することが無い部門は載せない。最後にもう1本で重複をまとめ、並べ直す。
対象の部門は hub.config.json の daily_report.departments。
手順と決まりは framework/03_日次報告.md、報告の書き方は shared/共通プロトコル_日次報告.md。
"""
import argparse
import concurrent.futures
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile

HUB = pathlib.Path(__file__).resolve().parent.parent
OUT = HUB / "dashboard" / "manager"
STATUS = OUT / "status.json"
KEEP_DAYS = 30
PARALLEL = 4
TIMEOUT = 600

CONFIG = HUB / "hub.config.json"


def load_config():
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8")).get("daily_report", {})
    except (OSError, ValueError):
        return {}


def load_depts():
    """毎日報告させる部門。足す・外すは hub.config.json の daily_report.departments を直す。"""
    depts = []
    for d in load_config().get("departments", []):
        if d.get("num") and d.get("agent") and (HUB / "agents" / d["agent"] / "CLAUDE.md").exists():
            depts.append({"num": str(d["num"]), "label": d.get("label") or d["agent"],
                          "agent": d["agent"], "model": d.get("model") or "sonnet"})
    return depts


DEPTS = load_depts()

LEVELS = {"🔴": "red", "🟡": "yellow", "🟢": "green"}
WEEK = "月火水木金土日"


def claude_bin():
    return shutil.which("claude") or str(pathlib.Path.home() / ".local/bin/claude")


def ask_claude(prompt, model, cwd, tools, actor=""):
    """claude -p を1回。返すのは (本文, エラー文)。"""
    cmd = [claude_bin(), "-p", "--model", model, "--output-format", "json", "--strict-mcp-config"]
    if tools:
        cmd += ["--allowedTools", ",".join(tools),
                "--disallowedTools", "Write,Edit,NotebookEdit,WebSearch,WebFetch,Agent"]
    else:
        cmd += ["--tools", ""]
    try:
        # ダッシュボードのフックが、どの部門の動きかを見分けるための名乗り
        env = {**os.environ, "AGENT_HUB_ACTOR": actor} if actor else None
        p = subprocess.run(cmd, input=prompt, cwd=str(cwd), capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=TIMEOUT, env=env)
    except OSError:
        return None, "claudeコマンドが見つからない（Claude Codeが入っているか確かめる）"
    except subprocess.TimeoutExpired:
        return None, f"{TIMEOUT // 60}分たっても終わらなかった"
    try:
        data = json.loads(p.stdout)
    except ValueError:
        return None, (p.stderr.strip() or p.stdout.strip() or f"終了コード{p.returncode}")[-120:]
    if p.returncode != 0 or data.get("is_error"):
        why = str(data.get("result", "")) or f"終了コード{p.returncode}"
        if "authenticate" in why or "OAuth" in why or "login" in why.lower():
            why = "claudeコマンドのログインが切れている（ターミナルで claude を開いて /login）"
        return None, why[-120:]
    return data.get("result", ""), None


def dept_prompt(dept, today, yesterday_item):
    if yesterday_item:
        prev = f"{yesterday_item['title']}／{yesterday_item['body']}"
    else:
        prev = "なし"
    return (
        f"【委任】{dept['agent']} エージェント\n"
        f"必読: まず agents/{dept['agent']}/CLAUDE.md と shared/共通プロトコル.md と "
        f"shared/共通プロトコル_日次報告.md をReadし従うこと\n"
        f"指示: 【日次報告】を実行（今日は{today.isoformat()}（{WEEK[today.weekday()]}））\n"
        f"補足: 昨日この部門が出した報告＝{prev}\n"
    )


def parse_report(text):
    """共通プロトコル_日次報告.md の形から拾う。形が崩れていたら None。"""
    def field(name):
        m = re.search(rf"^\s*[-・*]?\s*{name}\s*[:：]\s*(.+)$", text, re.M)
        return m.group(1).strip() if m else ""

    state = field("状態")
    if "報告なし" in state:
        return {"has": False}
    if "報告あり" not in state:
        return None
    title, body = field("見出し"), field("本文")
    if not title:
        return None
    level = "yellow"
    for mark, name in LEVELS.items():
        if mark in field("緊急度"):
            level = name
    tail = text.split("根拠ファイル", 1)[1] if "根拠ファイル" in text else ""
    paths = [m.strip().strip("`") for m in re.findall(r"^\s*[-・*]\s*(.+)$", tail, re.M)]
    return {"has": True, "level": level, "title": title, "body": body, "paths": paths}


def evidence_ok(paths):
    """根拠ファイル欄に、実在するファイルが1つでもあるか。"""
    for raw in paths:
        # 「パス（補足）」の補足を外す。フォルダ名に半角の ( が入ることがあるので、切るのは全角だけ
        for p in (raw.strip(), raw.split("（", 1)[0].strip()):
            # 指示書を読んだだけではデータを見たことにならない
            if not p or p.startswith("web:") or "CLAUDE.md" in p or "共通プロトコル" in p:
                continue
            full = pathlib.Path(p).expanduser()
            if not full.is_absolute():
                full = HUB / p
            if full.exists():
                return True
    return False


def run_dept(dept, today, yesterday_item):
    text, err = ask_claude(dept_prompt(dept, today, yesterday_item), dept["model"], HUB,
                           ["Read", "Glob", "Grep", "Bash"], actor="cm-" + dept["agent"])
    base = {"dept": dept["num"], "label": dept["label"]}
    if err:
        return {**base, "result": "failed", "reason": err, "raw": ""}
    rep = parse_report(text)
    if rep is None:
        return {**base, "result": "failed", "reason": "報告が決まった形になっていない", "raw": text}
    if not rep["has"]:
        return {**base, "result": "silent", "raw": text}
    if not evidence_ok(rep["paths"]):
        return {**base, "result": "failed", "reason": "根拠ファイルが確認できない（不採用）", "raw": text}
    return {**base, "result": "report", "level": rep["level"], "title": rep["title"],
            "body": rep["body"], "raw": text}


MANAGER_PROMPT = """あなたは「Claude manager」。各部門から届いた今日の報告を、ダッシュボードに短く載せる形に整える。

本人の優先順位（上ほど優先）: {priorities}

決まり:
- 報告に書かれていない事実・数字を足さない。推測で埋めない。
- 同じ根の話が複数部門から来ていたら1件にまとめ、depts に部門番号を並べる。
- 緊急度は全体を見て付け直してよい（red=今日中／yellow=今週中／green=今月中）。
- title は30字以内、body は80字以内。数字と期限を残し、敬語で言い切る。4桁以上の数字はカンマ区切り。
- title は「何が起きているか」を書く。「〜する」「〜を決める」のような指図の形にしない。
- 本人が決めること（いつ作る・いつ練習する・何から始める）に期限や段取りを付けない。報告に無い手順を作らない。
- 並びは red → yellow → green。同じ緊急度の中は優先順位の高い順。
- hitokoto は、今日いちばん先に知っておくべき事実を60字以内で。指図にしない。報告が1件だけなら空文字でよい。

出力は次のJSONだけ（前後に文章もコードブロックも付けない）:
{{"hitokoto": "...", "items": [{{"depts": ["01"], "level": "red", "title": "...", "body": "..."}}]}}

届いた報告:
"""


def manage(reports):
    """重複をまとめて並べ直す。失敗したら部門の報告をそのまま使う。"""
    order = {"red": 0, "yellow": 1, "green": 2}
    plain = sorted(
        [{"depts": [r["dept"]], "level": r["level"], "title": r["title"], "body": r["body"]} for r in reports],
        key=lambda i: order[i["level"]])
    if len(reports) < 2:
        return "", plain, None
    lines = "\n".join(
        f"- 部門{r['dept']} {r['label']}／緊急度{r['level']}／見出し: {r['title']}／本文: {r['body']}" for r in reports)
    with tempfile.TemporaryDirectory() as tmp:
        head = MANAGER_PROMPT.format(priorities=load_config().get("priorities") or "指定なし")
        text, err = ask_claude(head + lines, "sonnet", tmp, None)
    if err:
        return "", plain, f"まとめに失敗（{err}）。部門の報告をそのまま載せた"
    m = re.search(r"\{.*\}", text, re.S)
    try:
        data = json.loads(m.group(0))
        known = {r["dept"] for r in reports}
        items = []
        for it in data["items"]:
            depts = [d for d in it["depts"] if d in known]
            if not depts or it["level"] not in order or not it["title"]:
                raise ValueError
            items.append({"depts": depts, "level": it["level"],
                          "title": str(it["title"]), "body": str(it.get("body", ""))})
        items.sort(key=lambda i: order[i["level"]])
        return str(data.get("hitokoto", "")), items, None
    except (AttributeError, KeyError, TypeError, ValueError):
        return "", plain, "まとめが読めなかった。部門の報告をそのまま載せた"


def latest_file(before=None):
    files = sorted(p for p in OUT.glob("20??-??-??.json") if before is None or p.stem < before)
    return files[-1] if files else None


def write_json(path, data):
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def run(force, only):
    if not DEPTS:
        print("報告させる部門がない（hub.config.json の daily_report.departments を確かめる）")
        return 1
    OUT.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today()
    target = OUT / f"{today.isoformat()}.json"
    if target.exists() and not force and not only:
        print("今日の分はもうある")
        return 0

    depts = [d for d in DEPTS if not only or d["num"] in only]
    prev = {}
    last = latest_file(before=today.isoformat())
    if last:
        for r in json.loads(last.read_text(encoding="utf-8")).get("depts", []):
            if r["result"] == "report":
                prev[r["dept"]] = r

    started = datetime.datetime.now().isoformat(timespec="seconds")
    write_json(STATUS, {"state": "running", "started": started, "done": 0, "total": len(depts)})
    results = []
    try:
        with concurrent.futures.ThreadPoolExecutor(PARALLEL) as pool:
            jobs = [pool.submit(run_dept, d, today, prev.get(d["num"])) for d in depts]
            for job in concurrent.futures.as_completed(jobs):
                results.append(job.result())
                write_json(STATUS, {"state": "running", "started": started,
                                    "done": len(results), "total": len(depts)})
                r = results[-1]
                print(f"{r['dept']} {r['label']}: {r['result']} {r.get('reason', r.get('title', ''))}", flush=True)

        results.sort(key=lambda r: [d["num"] for d in DEPTS].index(r["dept"]))
        reports = [r for r in results if r["result"] == "report"]
        hitokoto, items, note = manage(reports)
        write_json(target, {
            "date": today.isoformat(),
            "generated": datetime.datetime.now().isoformat(timespec="seconds"),
            "hitokoto": hitokoto,
            "items": items,
            "failed": [{"dept": r["dept"], "label": r["label"], "reason": r["reason"]}
                       for r in results if r["result"] == "failed"],
            "note": note or "",
            "asked": len(results),
            "depts": results,
        })
    finally:
        write_json(STATUS, {"state": "idle"})

    for old in sorted(OUT.glob("20??-??-??.json"))[:-KEEP_DAYS]:
        old.unlink()
    failed = sum(r["result"] == "failed" for r in results)
    print(f"報告あり{len(reports)}／なし{len(results) - len(reports) - failed}／受け取れず{failed}")
    return 1 if failed == len(results) else 0


def latest():
    """ダッシュボード用。部門の生の報告は外して返す。"""
    out = {"report": None, "status": {"state": "idle"}}
    f = latest_file() if OUT.exists() else None
    if f:
        data = json.loads(f.read_text(encoding="utf-8"))
        data.pop("depts", None)
        label = {d["num"]: d["label"] for d in load_depts()}
        for it in data["items"]:
            it["names"] = [label.get(n, n) for n in it["depts"]]
        out["report"] = data
    try:
        out["status"] = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        pass
    return out


def show():
    rep = latest()["report"]
    if not rep:
        print("まだ報告がない")
        return 0
    label = {d["num"]: d["label"] for d in load_depts()}
    mark = {v: k for k, v in LEVELS.items()}
    print(f"{rep['date']} の報告（{rep['generated'][11:16]} 受信）")
    if rep["hitokoto"]:
        print("今日の一手:", rep["hitokoto"])
    for it in rep["items"]:
        names = "・".join(label.get(d, d) for d in it["depts"])
        print(f"{mark[it['level']]} [{names}] {it['title']} — {it['body']}")
    if not rep["items"]:
        print("報告はなし")
    for f in rep["failed"]:
        print(f"受け取れず: {f['label']}（{f['reason']}）")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "show"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    if a.cmd == "show":
        sys.exit(show())
    sys.exit(run(a.force, {x.strip() for x in a.only.split(",") if x.strip()}))
