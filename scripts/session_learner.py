#!/usr/bin/env python3
"""会話ログから学ぶ。前回からのオーナーとのやりとりを読み返し、繰り返された訂正をメモリに足す。

  python3 scripts/session_learner.py run              # 前回の続きから読む（日次報告が毎朝、集める前に呼ぶ）
  python3 scripts/session_learner.py run --days 7     # 直近7日を読み直す（読んだ位置は進めない）
  python3 scripts/session_learner.py run --dry        # 何を覚えるかだけ出す。どこにも書かない
  python3 scripts/session_learner.py show             # 最後に覚えたこと・様子見の件数
  python3 scripts/session_learner.py list             # 様子見も含めた全候補
  python3 scripts/session_learner.py undo 12          # 12番を取り消す（メモリを元に戻し、二度と覚えない）

流れは3段。①会話ごとに claude -p で「訂正・恒久の指示・答えた確認・手で頼んだ定型作業」を拾う。
②拾ったものを、様子見の候補と今のメモリに突き合わせる。③別々の会話で2回見たものを
メモリに書く。メモリに書いたあとの会話でまた直された訂正は、そのメモリを書き直す。
決まりは framework/06_会話ログからの学習.md。Windowsでは python3 の代わりに python。
"""
import argparse
import concurrent.futures
import datetime
import hashlib
import json
import os
import pathlib
import re
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from claude_manager import ask_claude  # noqa: E402

HUB = pathlib.Path(__file__).resolve().parent.parent
OUT = HUB / "dashboard" / "learner"
STATE = OUT / "state.json"
LEDGER = OUT / "candidates.json"
CACHE = OUT / "spot_cache.json"   # 読み直しのたびに同じ会話を claude に渡さないための控え
# Claude Code は会話ログを ~/.claude/projects/（フォルダのパスの英数字以外を - に置き換えた名前）に置く
LOGS = pathlib.Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(HUB))
MEMORY = LOGS / "memory"
INDEX = MEMORY / "MEMORY.md"

PARALLEL = 4
FIRST_DAYS = 7         # 初回に読み返す日数
KEEP_DAYS = 30
CHUNK = 50000          # 1回に渡す会話の長さ（字）
NEED = {"correction": 2, "answer": 2, "standing": 2, "request": 3}   # 別々の会話で何回見たら動くか
KINDS = {"correction": "訂正", "standing": "恒久の指示", "answer": "答えた確認", "request": "手で頼んだ作業"}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, path)


def read_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def parse_ts(s):
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00"))


# ── 会話ログを読む ──────────────────────────────────────────

NOISE = re.compile(r"<(system-reminder|local-command-[a-z]+|command-[a-z]+|task-notification)\b[\s\S]*?</\1>")


def human_text(d):
    """本人が打った文だけ返す。道具の結果・自動の通知・claude -p の指示は None。"""
    if d.get("type") != "user" or d.get("isMeta") or d.get("isSidechain"):
        return None
    if d.get("entrypoint") == "sdk-cli" or d.get("promptSource") == "system":
        return None
    origin = d.get("origin")
    if isinstance(origin, dict) and origin.get("kind") != "human":
        return None
    content = d.get("message", {}).get("content")
    if isinstance(content, list):
        if any(b.get("type") == "tool_result" for b in content if isinstance(b, dict)):
            return None
        content = "\n".join(b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text")
    if not isinstance(content, str):
        return None
    text = NOISE.sub("", content).strip()
    return text or None


def assistant_text(d):
    parts = []
    for b in d.get("message", {}).get("content", []) or []:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text":
            parts.append(b.get("text", ""))
        elif b.get("type") == "tool_use" and b.get("name") == "AskUserQuestion":
            qs = [q.get("question", "") for q in b.get("input", {}).get("questions", [])]
            parts.append("（確認の質問）" + " / ".join(qs))
    return "\n".join(p for p in parts if p).strip()


def read_session(path, since, until, seen):
    """1会話ぶんの (やりとりの文字起こし, 最後に読んだ時刻)。期間内に本人の発言が無ければ None。"""
    turns, said, last_agent = [], 0, ""
    newest, start = None, None
    try:
        lines = path.open(encoding="utf-8", errors="replace")
    except OSError:
        return None
    with lines:
        for line in lines:
            if '"type":"user"' not in line and '"type":"assistant"' not in line:
                continue
            try:
                d = json.loads(line)
            except ValueError:
                continue
            if d.get("type") == "assistant" and not d.get("isSidechain"):
                t = assistant_text(d)
                if t:
                    last_agent = t
                continue
            text = human_text(d)
            if not text or not d.get("timestamp"):
                continue
            # 会話を分岐させると、同じ発言が別のファイルにも写る。二重に数えない
            if d.get("uuid") in seen:
                last_agent = ""
                continue
            seen.add(d.get("uuid"))
            ts = parse_ts(d["timestamp"])
            if ts > until:
                break
            if last_agent:
                tail = last_agent if len(last_agent) <= 700 else "…" + last_agent[-700:]
                turns.append((ts, "【エージェント】" + tail))
                last_agent = ""
            turns.append((ts, "【本人】" + text[:2500]))
            start = start or ts
            if ts > since:
                said += 1
                newest = ts
    if not said:
        return None
    # 期間より前のやりとりは、文脈として直前の少しだけ残す
    first = next(i for i, (ts, _) in enumerate(turns) if ts > since)
    kept = turns[max(0, first - 4):]
    return "\n\n".join(t for _, t in kept), newest, start


def collect(since, until):
    sessions, seen = [], set()
    for path in sorted(LOGS.glob("*.jsonl"), key=lambda p: p.stat().st_mtime):
        if datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc) < since:
            continue
        got = read_session(path, since, until, seen)
        if got:
            text, newest, start = got
            day = newest.astimezone().date().isoformat()
            for i in range(0, len(text), CHUNK):
                sessions.append({"session": path.stem, "date": day, "start": start.isoformat(),
                                 "text": text[i:i + CHUNK]})
    return sessions


# ── ①拾う ────────────────────────────────────────────────

SPOT_PROMPT = """あなたは、ある人（本人）とAIエージェントの会話の記録を読み返し、「次からは本人に言わせずに済むこと」を拾う係。

拾うのは次の4種類だけ。
- correction: エージェントの出力・やり方・判断を本人が直した、やり直させた、不満を言った。
- standing: 本人が「今後は」「毎回」「必ず」「二度と」のように、この先ずっとの決まりとして言った。
- answer: エージェントが本人に確認・質問し、本人が答えた。同じ種類の作業でまた聞くことになりそうなもの。
- request: 本人が手で頼んだ、決まった形の繰り返し作業（毎日・毎週また頼みそうなもの）。

決まり:
- rule は「次に同じ種類の作業をするエージェントが、最初から守れる形」の一文にする。この会話の固有の物（特定の文・特定の画面・特定の数字）の手直しでしかなく、次の作業に持ち越せないものは拾わない。
- 本人の指示が一回限りの作業依頼そのものであるとき（「これを作って」「ここを青にして」）は拾わない。直しの中に、次にも通じる好み・基準があるときだけ拾う。
- 冗談・雑談・本人の気持ちの話は拾わない。
- quote は本人の言葉を40字以内でそのまま抜く。作らない。
- scope は、その決まりが効く場面（例: 文章の作成／メール／家計の記録／調べもの／司令塔の応答全般）。
- 何も無ければ空の配列でよい。無理に探さない。

出力は次のJSONだけ（前後に文章もコードブロックも付けない）:
{"found": [{"kind": "correction", "rule": "...", "quote": "...", "scope": "..."}]}

会話の記録:
"""


def parse_json(text):
    m = re.search(r"\{[\s\S]*\}", text or "")
    try:
        return json.loads(m.group(0))
    except (AttributeError, ValueError):
        return None


def spot(sess, cache):
    key = hashlib.sha1((sess["session"] + sess["text"]).encode()).hexdigest()
    if key in cache:
        return cache[key]["found"], None
    found, err = spot_fresh(sess)
    if not err:
        cache[key] = {"date": sess["date"], "found": found}
    return found, err


def spot_fresh(sess):
    with tempfile.TemporaryDirectory() as tmp:
        text, err = ask_claude(SPOT_PROMPT + sess["text"], "sonnet", tmp, None, actor="learner")
    if err:
        return None, err
    data = parse_json(text)
    if data is None or not isinstance(data.get("found"), list):
        return None, "返事が決まった形になっていない"
    found = []
    for f in data["found"]:
        if isinstance(f, dict) and f.get("kind") in NEED and f.get("rule"):
            found.append({"kind": f["kind"], "rule": str(f["rule"]), "quote": str(f.get("quote", ""))[:60],
                          "scope": str(f.get("scope", "")), "session": sess["session"], "date": sess["date"],
                          "start": sess["start"]})
    return found, None


# ── ②突き合わせる ──────────────────────────────────────────

MATCH_PROMPT = """会話の記録から拾った「観察」を、すでに様子見している「候補」と、すでに覚えている「メモリ」に突き合わせる。

決まり:
- 観察ごとに、同じ決まりを指しているものを1つ選ぶ。言い回しが違っても、守れば同じ直しが要らなくなるなら同じとみる。場面が違うだけで中身が別なら別とみる。
- 候補に当たれば "c番号"（例 "c12"）、メモリに当たればそのファイル名（例 "feedback-xxx.md"）、どちらにも無ければ "new"。
- 観察どうしが同じ決まりなら、後ろの観察は前の観察を "o番号"（例 "o3"）で指す。
- 迷ったら "new"。無理に寄せない。

出力は次のJSONだけ（前後に文章もコードブロックも付けない）。観察の数だけ並べる:
{"match": [{"o": 0, "to": "new"}]}
"""


def match(found, ledger):
    watching = ledger["items"]   # 取り消したものも並べる（当たったら黙って捨てるため）
    lines = ["# 観察"] + [f"o{i} [{f['kind']}／{f['scope']}] {f['rule']}" for i, f in enumerate(found)]
    lines += ["", "# 候補"] + [f"c{c['id']} [{c['kind']}／{c['scope']}] {c['rule']}" for c in watching]
    lines += ["", "# メモリ", INDEX.read_text(encoding="utf-8") if INDEX.exists() else ""]
    with tempfile.TemporaryDirectory() as tmp:
        text, err = ask_claude(MATCH_PROMPT + "\n".join(lines), "opus", tmp, None, actor="learner")
    if err:
        return None, err
    data = parse_json(text)
    if data is None or not isinstance(data.get("match"), list):
        return None, "突き合わせの返事が読めなかった"
    to = {}
    for m in data["match"]:
        if isinstance(m, dict) and isinstance(m.get("o"), int):
            to[m["o"]] = str(m.get("to", "new"))
    return to, None


def absorb(found, to, ledger):
    """観察を台帳に足す。返すのは今回さわった候補のid。"""
    by_id = {c["id"]: c for c in ledger["items"]}
    placed, touched = {}, []
    for i, f in enumerate(found):
        target = to.get(i, "new")
        cand = None
        if re.fullmatch(r"c\d+", target):
            cand = by_id.get(int(target[1:]))
        elif re.fullmatch(r"o\d+", target):
            cand = placed.get(int(target[1:]))
        elif target.endswith(".md") and (MEMORY / target).exists():
            cand = next((c for c in ledger["items"] if c.get("memory") == target), None)
            if cand is None:
                cand = {"id": ledger["next_id"], "kind": f["kind"], "rule": f["rule"], "scope": f["scope"],
                        "status": "known", "memory": target, "sightings": []}
                ledger["next_id"] += 1
                ledger["items"].append(cand)
                by_id[cand["id"]] = cand
        if cand is None:
            cand = {"id": ledger["next_id"], "kind": f["kind"], "rule": f["rule"], "scope": f["scope"],
                    "status": "watching", "memory": "", "sightings": []}
            ledger["next_id"] += 1
            ledger["items"].append(cand)
            by_id[cand["id"]] = cand
        placed[i] = cand
        q = f["quote"].strip()
        if q and any(s["quote"].strip().startswith(q) or q.startswith(s["quote"].strip() or "\0")
                     for s in cand["sightings"]):
            continue
        cand["sightings"].append({"session": f["session"], "date": f["date"], "start": f["start"],
                                  "quote": f["quote"], "new": True})
        # 恒久の指示が一度でも出たら、候補ごと恒久の指示として扱う
        if f["kind"] == "standing" and cand["kind"] in ("correction", "answer"):
            cand["kind"] = "standing"
        if cand["id"] not in touched:
            touched.append(cand["id"])
    return touched


def sessions_of(cand, only_new=False):
    return {s["session"] for s in cand["sightings"] if s.get("new") or not only_new}


def decide(cand):
    """今回この候補に何をするか。learn＝メモリに書く／sharpen＝あるメモリを書き直す／automate＝自動化の候補に出す。"""
    if cand["status"] == "rejected" or cand.get("frozen"):
        return None
    if cand["kind"] == "request":
        if cand["status"] == "watching" and len(sessions_of(cand)) >= NEED["request"]:
            return "automate"
        return None
    if cand["status"] == "watching":
        return "learn" if len(sessions_of(cand)) >= NEED[cand["kind"]] else None
    # known（もとからメモリにある）・learned（前に覚えた）のに、また直された。
    # メモリを書いた会話そのものは数えない。メモリができたあとに始まった会話で直されたときだけ
    path = MEMORY / cand.get("memory", "")
    if cand["kind"] in ("correction", "standing") and path.is_file():
        written = datetime.datetime.fromtimestamp(path.stat().st_mtime, datetime.timezone.utc)
        if any(s.get("new") and parse_ts(s["start"]) > written for s in cand["sightings"]):
            return "sharpen"
    return None


# ── ③覚える ────────────────────────────────────────────────

WRITE_PROMPT = """本人とAIエージェントの会話で繰り返し出てきた決まりを、エージェントが次の会話から読む「メモリ」1件として書く。

決まり:
- 本人の言葉（quote）から外れた内容を足さない。理由が言葉から読み取れないときは、理由を作らず「別々の会話で繰り返し直された」とだけ書き、日付を添える。
- body は、まず決まりを1〜2文で言い切り、空行のあと「**Why:**」の行、空行のあと「**How to apply:**」の行を続ける。How to apply には、どの場面で・どのエージェントが・何をするかを書く。サブエージェントの作業に効く決まりなら「委任文にも書く」と入れる。
- name は英小文字とハイフンだけの短い名前（feedback- で始める）。
- description は、この決まりが関係する場面かどうかを一行で判断できる文。
- title は目次用の短い見出し（20字以内）、hook はその補足（30字以内）。
- 「今あるメモリ」が渡されたときは、それを書き直す。もとの内容・日付・固有名詞は削らず、また直された場面にも効くように、当てはまる範囲とやることを具体的にする。name は変えない。

出力は次のJSONだけ（前後に文章もコードブロックも付けない）:
{"name": "feedback-...", "description": "...", "title": "...", "hook": "...", "body": "..."}
"""

FRONT = re.compile(r"\A---\n([\s\S]*?)\n---\n")


def write_memory(cand, action, today):
    old_file = MEMORY / cand["memory"] if action == "sharpen" else None
    old = old_file.read_text(encoding="utf-8") if old_file and old_file.exists() else ""
    if action == "sharpen" and not old:
        return None, "書き直すメモリが見つからない"
    said = "\n".join(f"- {s['date']}「{s['quote']}」" for s in cand["sightings"])
    prompt = (WRITE_PROMPT + f"\n今日: {today}\n種類: {KINDS[cand['kind']]}\n場面: {cand['scope']}\n"
              f"決まり（仮）: {cand['rule']}\n本人の言葉:\n{said}\n")
    if old:
        prompt += f"\n今あるメモリ（{cand['memory']}）:\n{old}\n"
    with tempfile.TemporaryDirectory() as tmp:
        text, err = ask_claude(prompt, "opus", tmp, None, actor="learner")
    if err:
        return None, err
    data = parse_json(text)
    if not data or not data.get("body") or not data.get("description"):
        return None, "メモリの下書きが読めなかった"
    now = datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    desc = " ".join(str(data["description"]).split())
    if old:
        m = FRONT.match(old)
        head = m.group(1) if m else f"name: {old_file.stem}\ndescription: {desc}\nmetadata:\n  type: feedback"
        head = re.sub(r"^description:.*$", lambda _: "description: " + desc, head, count=1, flags=re.M)
        head = re.sub(r"^(\s*)modified:.*$", lambda mm: f"{mm.group(1)}modified: {now}", head, flags=re.M)
        path = old_file
    else:
        slug = re.sub(r"[^a-z0-9-]", "", str(data.get("name", "")).lower()).strip("-") or f"feedback-learned-{cand['id']}"
        if not slug.startswith("feedback-"):
            slug = "feedback-" + slug
        path = MEMORY / f"{slug}.md"
        if path.exists():
            path = MEMORY / f"{slug}-{cand['id']}.md"
        head = (f"name: {path.stem}\ndescription: {desc}\nmetadata:\n  node_type: memory\n  type: feedback\n"
                f"  learnedBy: session_learner\n  modified: {now}")
    return {"path": path, "text": f"---\n{head}\n---\n\n{str(data['body']).strip()}\n",
            "title": str(data.get("title") or cand["rule"])[:30], "hook": str(data.get("hook", ""))[:40],
            "old": old}, None


def add_index(filename, title, hook):
    lines = INDEX.read_text(encoding="utf-8").rstrip("\n").split("\n") if INDEX.exists() else ["# Memory Index", ""]
    if any(f"]({filename})" in l for l in lines):
        return
    lines.append(f"- [{title}]({filename})" + (f" — {hook}" if hook else ""))
    INDEX.write_text("\n".join(lines) + "\n", encoding="utf-8")


def drop_index(filename):
    if not INDEX.exists():
        return
    lines = [l for l in INDEX.read_text(encoding="utf-8").split("\n") if f"]({filename})" not in l]
    INDEX.write_text("\n".join(lines), encoding="utf-8")


# ── 実行 ──────────────────────────────────────────────────

def load_ledger():
    return read_json(LEDGER, {"next_id": 1, "items": []})


def run(days, dry):
    if not LOGS.exists():
        print(f"会話ログの置き場が見つからない（{LOGS}）。このフォルダで claude を一度使ってから走らせる")
        return 1
    MEMORY.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now(datetime.timezone.utc)
    state = read_json(STATE, {})
    replay = days is not None
    if replay:
        since = now - datetime.timedelta(days=days)
    elif state.get("last_ts"):
        since = parse_ts(state["last_ts"])
    else:
        since = now - datetime.timedelta(days=FIRST_DAYS)
    today = datetime.date.today().isoformat()

    sessions = collect(since, now)
    print(f"{since.astimezone():%m/%d %H:%M} 以降の会話 {len({s['session'] for s in sessions})}件を読む", flush=True)
    found, failed = [], []
    cache = read_json(CACHE, {})
    with concurrent.futures.ThreadPoolExecutor(PARALLEL) as pool:
        for sess, (got, err) in zip(sessions, pool.map(lambda x: spot(x, cache), sessions)):
            if err:
                failed.append(f"{sess['session'][:8]}: {err}")
            else:
                found += got
    limit = (datetime.date.today() - datetime.timedelta(days=KEEP_DAYS)).isoformat()
    write_json(CACHE, {k: v for k, v in cache.items() if v["date"] >= limit})
    print(f"拾った観察 {len(found)}件／読めなかった会話 {len(failed)}件", flush=True)
    if sessions and len(failed) == len(sessions):
        print("\n".join(failed))
        return 1

    ledger = load_ledger()
    for c in ledger["items"]:
        for s in c["sightings"]:
            s.pop("new", None)
    touched = []
    if found:
        to, err = match(found, ledger)
        if err:
            print("突き合わせに失敗:", err)
            return 1
        touched = absorb(found, to, ledger)

    result = {"date": today, "generated": datetime.datetime.now().isoformat(timespec="seconds"),
              "learned": [], "sharpened": [], "automation": [], "failed": failed, "dry": dry}
    by_id = {c["id"]: c for c in ledger["items"]}
    for cid in touched:
        cand = by_id[cid]
        action = decide(cand)
        if action == "automate":
            cand["status"] = "suggested"
            result["automation"].append({"id": cid, "title": cand["rule"],
                                         "times": len(sessions_of(cand)), "quotes": [s["quote"] for s in cand["sightings"]][:3]})
        elif action in ("learn", "sharpen"):
            mem, err = write_memory(cand, action, today)
            if err:
                result["failed"].append(f"候補{cid}: {err}")
                continue
            entry = {"id": cid, "title": mem["title"], "hook": mem["hook"], "file": mem["path"].name,
                     "kind": cand["kind"], "quotes": [s["quote"] for s in cand["sightings"]][-3:]}
            if dry:
                entry["draft"] = mem["text"]
            else:
                mem["path"].write_text(mem["text"], encoding="utf-8")
                if action == "learn":
                    add_index(mem["path"].name, mem["title"], mem["hook"])
                    cand["status"], cand["memory"] = "learned", mem["path"].name
                else:
                    cand.setdefault("history", []).append({"date": today, "text": mem["old"]})
                cand["changed"] = today
            result["learned" if action == "learn" else "sharpened"].append(entry)

    for label, key in (("覚えた", "learned"), ("書き直した", "sharpened"), ("自動化の候補", "automation")):
        for e in result[key]:
            print(f"{label} #{e['id']}: {e['title']}" + (f"（{e['file']}）" if e.get("file") else ""))
    for f in result["failed"]:
        print("失敗:", f)
    if dry:
        for e in result["learned"] + result["sharpened"]:
            print(f"\n── #{e['id']} の下書き ──\n{e['draft']}")
        print("\n── 様子見に入るもの ──")
        for cid in touched:
            c = by_id[cid]
            if c["status"] in ("watching", "known"):
                print(f"#{cid} [{KINDS[c['kind']]}／{c['status']}] {c['rule']}  ← " + " / ".join(s["quote"] for s in c["sightings"]))
        return 0

    write_json(LEDGER, ledger)
    if result["learned"] or result["sharpened"] or result["automation"] or not (OUT / f"{today}.json").exists():
        prev = read_json(OUT / f"{today}.json", None)
        if prev:   # 同じ日に2回走ったら、足し合わせる
            for key in ("learned", "sharpened", "automation", "failed"):
                result[key] = prev.get(key, []) + result[key]
        write_json(OUT / f"{today}.json", result)
    if not replay:
        write_json(STATE, {"last_ts": now.isoformat()})
    for old in sorted(OUT.glob("20??-??-??.json"))[:-KEEP_DAYS]:
        old.unlink()
    return 0


def latest():
    """日次報告・ダッシュボード用。いちばん新しい「覚えたこと」。24時間より前のものは出さない。"""
    files = sorted(OUT.glob("20??-??-??.json")) if OUT.exists() else []
    if not files:
        return None
    data = read_json(files[-1], None)
    if not data:
        return None
    age = datetime.datetime.now() - datetime.datetime.fromisoformat(data["generated"])
    if age > datetime.timedelta(hours=36):
        return None
    if not (data["learned"] or data["sharpened"] or data["automation"]):
        return None
    return {k: data[k] for k in ("date", "generated", "learned", "sharpened", "automation")}


def show():
    rep = latest()
    ledger = load_ledger()
    watching = sum(c["status"] == "watching" for c in ledger["items"])
    if not rep:
        print(f"この1日で新しく覚えたことはない（様子見 {watching}件）")
        return 0
    print(f"{rep['date']} に覚えたこと")
    for e in rep["learned"]:
        print(f"覚えた #{e['id']}: {e['title']} — {e['hook']}（{e['file']}）")
    for e in rep["sharpened"]:
        print(f"書き直した #{e['id']}: {e['title']}（{e['file']}。覚えていたのにまた直された）")
    for e in rep["automation"]:
        print(f"自動化の候補 #{e['id']}: {e['title']}（{e['times']}回頼まれた）")
    print(f"様子見 {watching}件。取り消すときは undo 番号")
    return 0


def show_list():
    for c in load_ledger()["items"]:
        mem = f" → {c['memory']}" if c.get("memory") else ""
        print(f"#{c['id']} [{c['status']}／{KINDS[c['kind']]}／{len(sessions_of(c))}会話] {c['rule']}{mem}")
        for s in c["sightings"]:
            print(f"    {s['date']}「{s['quote']}」")
    return 0


def undo(cid):
    ledger = load_ledger()
    cand = next((c for c in ledger["items"] if c["id"] == cid), None)
    if not cand:
        print(f"#{cid} は無い")
        return 1
    path = MEMORY / cand["memory"] if cand.get("memory") else None
    if cand.get("history"):
        last = cand["history"].pop()
        path.write_text(last["text"], encoding="utf-8")
        cand["frozen"] = True
        print(f"{cand['memory']} を書き直す前に戻した。今後このメモリは書き直さない")
    elif cand["status"] == "learned" and path and path.exists():
        path.unlink()
        drop_index(cand["memory"])
        cand["memory"] = ""
        print(f"{path.name} を消した")
    elif cand["status"] in ("watching", "suggested"):
        pass
    else:
        print(f"#{cid} は取り消すものが無い")
        return 1
    if cand["status"] in ("learned", "watching", "suggested") and not cand.get("frozen"):
        cand["status"] = "rejected"
        print(f"#{cid} は今後覚えない")
    write_json(LEDGER, ledger)
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["run", "show", "list", "undo"])
    ap.add_argument("id", nargs="?", type=int)
    ap.add_argument("--days", type=float)
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args()
    if a.cmd == "run":
        sys.exit(run(a.days, a.dry))
    if a.cmd == "show":
        sys.exit(show())
    if a.cmd == "list":
        sys.exit(show_list())
    if a.id is None:
        sys.exit("undo には番号が要る")
    sys.exit(undo(a.id))
