#!/usr/bin/env python3
"""
Agent Hub Dashboard Server
Usage: python3 server.py [port]   (default: 8765)
"""
import os, sys, json, time, threading, queue, re, subprocess, shutil
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from datetime import datetime

BASE_DIR      = Path(__file__).parent.parent        # agent-hub/
DASHBOARD_DIR = Path(__file__).parent               # agent-hub/dashboard/
LOG_FILE      = DASHBOARD_DIR / 'logs' / 'events.jsonl'
AGENTS_DIR    = BASE_DIR / 'agents'
REPORTS_DIR   = BASE_DIR / 'reports'
CLAUDE_PROJECTS      = Path.home() / '.claude' / 'projects'
SESSION_LABELS_FILE  = DASHBOARD_DIR / 'session_labels.json'

_sess_cache:   dict = {'data': None, 'ts': 0.0}
_sess_labels:  dict = {}

def _load_labels():
    global _sess_labels
    if SESSION_LABELS_FILE.exists():
        try:
            _sess_labels = json.loads(SESSION_LABELS_FILE.read_text(encoding='utf-8'))
        except Exception:
            _sess_labels = {}

def _save_labels():
    try:
        SESSION_LABELS_FILE.write_text(
            json.dumps(_sess_labels, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except Exception:
        pass

DEPT_LABELS = {
    '01': 'タスク管理',   '02': 'お金管理',     '03': 'ギター時間管理',
    '04': '仕事探し',     '05': '仕事実行',     '06': '進路リサーチ',
    '07': 'AI・IT情報',   '08': '体調管理',     '09': '大学',
    '10': '資産分析',     '11': '一人暮らし',    '12': '機材資産',
}
DEPT_COLORS = {
    '01': '#7aadff', '02': '#4caf6e', '03': '#c87fff',
    '04': '#d4a437', '05': '#d4a437', '06': '#52c8c8',
    '07': '#52c8ff', '08': '#e05252', '09': '#ffb347',
    '10': '#ffd700', '11': '#ff69b4', '12': '#c89000',
}

# ── SSE client registry ──────────────────────────────────────────────────────
_sse_clients: list[queue.Queue] = []
_sse_lock = threading.Lock()

def broadcast_sse(data: dict):
    msg = ('data: ' + json.dumps(data, ensure_ascii=False) + '\n\n').encode()
    with _sse_lock:
        dead = []
        for q in _sse_clients:
            try:
                q.put_nowait(msg)
            except Exception:
                dead.append(q)
        for q in dead:
            _sse_clients.remove(q)

def _tail_log():
    """Background thread: tail events.jsonl and broadcast new lines."""
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    with open(LOG_FILE, 'r', encoding='utf-8') as f:
        f.seek(0, 2)
        while True:
            line = f.readline()
            if line and line.strip():
                try:
                    broadcast_sse(json.loads(line))
                except Exception:
                    pass
            else:
                time.sleep(0.1)

def read_recent_events(n: int = 300) -> list:
    if not LOG_FILE.exists():
        return []
    try:
        text = LOG_FILE.read_text(encoding='utf-8').strip()
        if not text:
            return []
        events = []
        for line in text.split('\n')[-n:]:
            if line.strip():
                try:
                    events.append(json.loads(line))
                except Exception:
                    pass
        return events
    except Exception:
        return []

# ── Chat with Claude ─────────────────────────────────────────────────────────
def chat_with_claude(message: str, history: list) -> dict:
    """Run `claude --print` in BASE_DIR with conversation history."""
    claude_bin = shutil.which('claude') or 'claude'

    # Prepend recent history so Claude has context
    if history:
        hist_lines = []
        for h in history[-6:]:
            hist_lines.append(f"User: {h.get('user', '')}")
            hist_lines.append(f"Assistant: {h.get('assistant', '')}")
        prompt = "【これまでの会話履歴】\n" + "\n".join(hist_lines) + "\n\n【新しいメッセージ】\n" + message
    else:
        prompt = message

    try:
        proc = subprocess.run(
            [claude_bin, '--print', prompt],
            cwd=str(BASE_DIR),
            capture_output=True,
            text=True,
            timeout=300,
        )
        if proc.returncode == 0:
            # Strip ANSI escape codes if any
            text = re.sub(r'\x1b\[[0-9;]*m', '', proc.stdout).strip()
            return {'response': text}
        err = proc.stderr.strip() or f'exit code {proc.returncode}'
        return {'error': err}
    except subprocess.TimeoutExpired:
        return {'error': 'タイムアウト（5分）— 複雑な指示は分割してください'}
    except FileNotFoundError:
        return {'error': '`claude` コマンドが PATH に見つかりません。ターミナルで確認してください（Mac: `which claude` ／ Windows: `where claude`）。'}
    except Exception as e:
        return {'error': str(e)}


# ── Chat with Gemini (Antigravity Python SDK) ────────────────────────────────
def chat_with_gemini(message: str, history: list) -> dict:
    """Run Gemini using the Antigravity Python SDK with dynamic model selection."""
    import asyncio
    from google.antigravity import Agent, LocalAgentConfig, CapabilitiesConfig

    # Prepend recent history so Gemini has context
    if history:
        hist_lines = []
        for h in history[-6:]:
            hist_lines.append(f"User: {h.get('user', '')}")
            hist_lines.append(f"Assistant: {h.get('assistant', '')}")
        prompt = "【これまでの会話履歴】\n" + "\n".join(hist_lines) + "\n\n【新しいメッセージ】\n" + message
    else:
        prompt = message

    # Keyword-based model routing to mimic Claude Code's tiered approach
    msg_lower = message.lower()
    target_model = "gemini-2.5-pro"
    
    # Haiku equivalents -> Flash (01_task-manager, 04, 08 etc.)
    if "01_task-manager" in msg_lower or "haiku" in msg_lower or "04_job-searcher" in msg_lower or "08_health-manager" in msg_lower:
        target_model = "gemini-2.5-flash"
    # Opus equivalents -> 3.1 Pro (most capable)
    elif "opus" in msg_lower or "09_homework" in msg_lower:
        target_model = "gemini-3.1-pro"
    # Sonnet equivalents (default) -> 2.5 Pro
    else:
        target_model = "gemini-2.5-pro"

    async def _run_agent():
        config = LocalAgentConfig(
            model=target_model,
            system_instructions="あなたは司令塔エージェント（または指定されたサブエージェント）として振る舞います。必ず ./AGENTS.md や各種 CLAUDE.md に従ってタスクを遂行してください。",
            capabilities=CapabilitiesConfig()
        )
        async with Agent(config) as agent:
            response = await agent.chat(prompt)
            full_text = ""
            async for token in response:
                full_text += token
            return full_text

    try:
        result_text = asyncio.run(_run_agent())
        result_text = re.sub(r'\x1b\[[0-9;]*m', '', result_text).strip()
        return {'response': result_text}
    except Exception as e:
        return {'error': str(e)}



# ── Capabilities parser ──────────────────────────────────────────────────────
DEPT_COLOR = {
    '01': '#7aadff', '02': '#4caf6e', '03': '#c87fff',
    '04': '#d4a437', '05': '#d4a437', '06': '#52c8c8',
    '07': '#52c8ff', '08': '#e05252', '09': '#ffb347',
    '10': '#ffd700', '11': '#ff69b4', '12': '#c89000',
}

def _dept_color(folder: str) -> str:
    num = re.match(r'^(\d+)', folder)
    return DEPT_COLOR.get(num.group(1) if num else '', '#888')

def _parse_agent(agent_dir: Path) -> dict | None:
    claude_md = agent_dir / 'CLAUDE.md'
    if not claude_md.exists():
        return None
    try:
        content = claude_md.read_text(encoding='utf-8', errors='replace')
    except Exception:
        return None

    # Name from first # heading
    m = re.search(r'^#\s+(.+?)(?:\s*[—\-–]\s*CLAUDE\.md)?$', content, re.MULTILINE)
    name = m.group(1).strip() if m else agent_dir.name

    # Role paragraph
    m = re.search(r'## 役割\s*\n+([\s\S]+?)(?=\n##|\Z)', content)
    role = re.sub(r'\s+', ' ', m.group(1)).strip()[:180] if m else ''

    # Data sources table rows
    sources = []
    m = re.search(
        r'## データソース[\s\S]*?\|[^\n]+\|\s*\n\|[-|: ]+\|\s*\n((?:\|[^\n]+\|\s*\n)+)',
        content
    )
    if m:
        for row in m.group(1).strip().split('\n'):
            cells = [c.strip() for c in row.split('|') if c.strip()]
            if cells:
                sources.append({
                    'path':       cells[0] if len(cells) > 0 else '',
                    'permission': cells[1] if len(cells) > 1 else '',
                    'purpose':    cells[2] if len(cells) > 2 else '',
                })

    return {
        'id':      agent_dir.name,
        'name':    name,
        'role':    role,
        'sources': sources,
        'color':   _dept_color(agent_dir.name),
    }

_cap_cache: dict = {'data': None, 'ts': 0}

def get_capabilities() -> list:
    now = time.time()
    if now - _cap_cache['ts'] > 60:
        result = []
        if AGENTS_DIR.exists():
            for d in sorted(AGENTS_DIR.iterdir()):
                if d.is_dir():
                    a = _parse_agent(d)
                    if a:
                        result.append(a)
        _cap_cache['data'] = result
        _cap_cache['ts'] = now
    return _cap_cache['data']

# ── Reports lister ───────────────────────────────────────────────────────────
def list_reports() -> list:
    if not REPORTS_DIR.exists():
        return []
    files = []
    for f in sorted(REPORTS_DIR.iterdir(), reverse=True):
        if f.is_file() and not f.name.startswith('.'):
            stat = f.stat()
            files.append({
                'name':     f.name,
                'size':     stat.st_size,
                'modified': datetime.fromtimestamp(stat.st_mtime).isoformat(),
                'ext':      f.suffix.lower(),
            })
    return files

# ── Session transcript reader ────────────────────────────────────────────────
def _parse_transcript(path: Path) -> list:
    """Parse a Claude Code session JSONL into clean message dicts."""
    messages = []
    try:
        with open(path, 'r', encoding='utf-8', errors='replace') as f:
            for line in f:
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get('type', '')
                if t not in ('user', 'assistant'):
                    continue
                msg = obj.get('message', {})
                content = msg.get('content', '') if isinstance(msg, dict) else obj.get('content', '')
                text, tools = '', []
                if isinstance(content, str):
                    text = content
                elif isinstance(content, list):
                    # Skip pure tool-result messages (assistant tool call responses)
                    ctypes = {b.get('type') for b in content if isinstance(b, dict)}
                    if 'tool_result' in ctypes and 'text' not in ctypes:
                        continue
                    for b in content:
                        if not isinstance(b, dict):
                            continue
                        if b.get('type') == 'text':
                            text += b.get('text', '')
                        elif b.get('type') == 'tool_use':
                            inp = b.get('input', {})
                            arg = ''
                            if isinstance(inp, dict):
                                arg = (inp.get('path') or inp.get('command') or
                                       inp.get('query') or inp.get('description') or '')
                                if isinstance(arg, str):
                                    arg = arg.split('/')[-1][:40]
                            tools.append({'name': b.get('name', ''), 'arg': str(arg)[:40]})
                if not text.strip() and not tools:
                    continue
                messages.append({
                    'role': t,
                    'text': text.strip(),
                    'tools': tools,
                    'ts': obj.get('timestamp', ''),
                })
    except Exception:
        pass
    return messages


def list_sessions() -> list:
    """Discover all Claude Code sessions across all projects, newest first."""
    now = time.time()
    if now - _sess_cache['ts'] < 8 and _sess_cache['data'] is not None:
        return _sess_cache['data']
    items = []
    if CLAUDE_PROJECTS.exists():
        for pdir in CLAUDE_PROJECTS.iterdir():
            if not pdir.is_dir():
                continue
            for jf in pdir.glob('*.jsonl'):
                try:
                    items.append((jf.stat().st_mtime, pdir, jf))
                except Exception:
                    pass
    items.sort(key=lambda x: x[0], reverse=True)
    sessions = []
    for mtime, pdir, jf in items[:100]:
        try:
            preview = ''
            with open(jf, 'r', encoding='utf-8', errors='replace') as f:
                for line in f:
                    if not line.strip():
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get('type') == 'user':
                            msg = obj.get('message', {})
                            c = msg.get('content', '') if isinstance(msg, dict) else obj.get('content', '')
                            if isinstance(c, str) and c.strip():
                                preview = c.strip()[:100]
                                break
                            elif isinstance(c, list):
                                for b in c:
                                    if isinstance(b, dict) and b.get('type') == 'text' and b.get('text', '').strip():
                                        preview = b['text'].strip()[:100]
                                        break
                                if preview:
                                    break
                    except Exception:
                        pass
            sessions.append({
                'id': jf.stem,
                'project': pdir.name,
                'modified': datetime.fromtimestamp(mtime).isoformat(),
                'preview': preview,
                'label': _sess_labels.get(jf.stem, ''),
            })
        except Exception:
            pass
    _sess_cache.update({'data': sessions, 'ts': now})
    return sessions


def get_session_transcript(session_id: str) -> dict | None:
    """Find and parse a session transcript by its UUID."""
    if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', session_id):
        return None
    if not CLAUDE_PROJECTS.exists():
        return None
    for pdir in CLAUDE_PROJECTS.iterdir():
        if not pdir.is_dir():
            continue
        jf = pdir / (session_id + '.jsonl')
        if jf.exists():
            return {
                'session_id': session_id,
                'project': pdir.name,
                'messages': _parse_transcript(jf),
                'modified': datetime.fromtimestamp(jf.stat().st_mtime).isoformat(),
            }
    return None


# ── HTTP handler ─────────────────────────────────────────────────────────────
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # suppress access logs

    def _send_json(self, data, status: int = 200):
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type',  'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, PUT, DELETE, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

    def do_DELETE(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/session/'):
            sid = path[len('/api/session/'):]
            self._delete_session(sid)
        else:
            self.send_error(404)

    def _delete_session(self, session_id: str):
        if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', session_id):
            self._send_json({'error': 'invalid id'}, 400)
            return
        if not CLAUDE_PROJECTS.exists():
            self._send_json({'error': 'not found'}, 404)
            return
        for pdir in CLAUDE_PROJECTS.iterdir():
            if not pdir.is_dir():
                continue
            jf = pdir / (session_id + '.jsonl')
            if jf.exists():
                try:
                    jf.unlink()
                except Exception as e:
                    self._send_json({'error': str(e)}, 500)
                    return
                if session_id in _sess_labels:
                    del _sess_labels[session_id]
                    _save_labels()
                _sess_cache['ts'] = 0.0
                self._send_json({'ok': True})
                return
        self._send_json({'error': 'not found'}, 404)
    def do_POST(self):
        path = self.path.split('?')[0]
        if path == '/api/chat':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            backend = body.get('backend') or os.environ.get('AGENT_BACKEND', 'claude')
            if str(backend).lower() == 'gemini':
                result = chat_with_gemini(body.get('message', ''), body.get('history', []))
            else:
                result = chat_with_claude(body.get('message', ''), body.get('history', []))
            _sess_cache['ts'] = 0.0  # new session was created; invalidate list cache
            self._send_json(result)
        elif path == '/api/read_file':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            self._get_file(body.get('path', ''))
        else:
            self.send_error(404)

    def do_PUT(self):
        path = self.path.split('?')[0]
        if path.startswith('/api/session/') and path.endswith('/label'):
            sid = path[len('/api/session/'):-len('/label')]
            if not re.match(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', sid):
                self._send_json({'error': 'invalid id'}, 400)
                return
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length).decode('utf-8'))
            label  = body.get('label', '').strip()[:80]
            if label:
                _sess_labels[sid] = label
            elif sid in _sess_labels:
                del _sess_labels[sid]
            _save_labels()
            _sess_cache['ts'] = 0.0
            self._send_json({'ok': True, 'label': label})
        elif path.startswith('/api/agent/') and path.endswith('/claude_md'):
            folder = path[len('/api/agent/'):-len('/claude_md')]
            length = int(self.headers.get('Content-Length', 0))
            body   = json.loads(self.rfile.read(length).decode('utf-8'))
            self._put_claude_md(folder, body.get('content', ''))
        elif path == '/api/write_file':
            length = int(self.headers.get('Content-Length', 0))
            body = json.loads(self.rfile.read(length).decode('utf-8'))
            self._put_file(body.get('path', ''), body.get('content', ''))
        else:
            self.send_error(404)

    def do_GET(self):
        path = self.path.split('?')[0]

        if path in ('/', '/index.html'):
            self._serve_static('index.html', 'text/html; charset=utf-8')
        elif path == '/galaxy':
            self._serve_static('galaxy.html', 'text/html; charset=utf-8')
        elif path == '/api/galaxy':
            self._send_json(get_galaxy())
        elif path == '/api/events':
            self._send_json(read_recent_events())
        elif path == '/api/events/stream':
            self._serve_sse()
        elif path == '/api/capabilities':
            self._send_json(get_capabilities())
        elif path == '/api/reports':
            self._send_json(list_reports())
        elif path == '/api/graph':
            self._send_json(get_graph())
        elif path == '/api/stats':
            stats_path = BASE_DIR / 'dashboard' / 'system_stats.json'
            if stats_path.exists():
                try:
                    self._send_json(json.loads(stats_path.read_text(encoding='utf-8')))
                except:
                    self._send_json({})
            else:
                self._send_json({})
        elif path == '/api/sessions':
            self._send_json(list_sessions())
        elif path.startswith('/api/session/') and path.endswith('/transcript'):
            sid = path[len('/api/session/'):-len('/transcript')]
            r = get_session_transcript(sid)
            self._send_json(r if r else {'error': 'not found'}, 200 if r else 404)
        elif path.startswith('/api/agent/') and path.endswith('/claude_md'):
            folder = path[len('/api/agent/'):-len('/claude_md')]
            self._get_claude_md(folder)
        elif path.startswith('/reports/'):
            self._serve_report(path[len('/reports/'):])
        else:
            self.send_error(404)

    def _agent_claude_path(self, folder: str):
        """Validate folder and return Path to its CLAUDE.md (or None if invalid)."""
        if folder == '_commander':
            return BASE_DIR / 'CLAUDE.md'
        if not re.match(r'^[a-zA-Z0-9_\-]{1,80}$', folder):
            return None
        p = (AGENTS_DIR / folder / 'CLAUDE.md').resolve()
        try:
            p.relative_to(AGENTS_DIR.resolve())
        except ValueError:
            return None
        return p if p.exists() else None

    def _get_claude_md(self, folder: str):
        fp = self._agent_claude_path(folder)
        if fp is None:
            self._send_json({'error': 'not found'}, 404)
            return
        try:
            content = fp.read_text(encoding='utf-8')
        except Exception as e:
            self._send_json({'error': str(e)}, 500)
            return
        rel = str(fp.relative_to(BASE_DIR))
        self._send_json({'folder': folder, 'path': rel, 'content': content})

    def _put_claude_md(self, folder: str, content: str):
        if folder == '_commander':
            fp = BASE_DIR / 'CLAUDE.md'
        else:
            if not re.match(r'^[a-zA-Z0-9_\-]{1,80}$', folder):
                self._send_json({'error': 'invalid folder'}, 400)
                return
            fp = AGENTS_DIR / folder / 'CLAUDE.md'
            try:
                fp.resolve().relative_to(AGENTS_DIR.resolve())
            except ValueError:
                self._send_json({'error': 'path traversal blocked'}, 400)
                return
            if not fp.exists():
                self._send_json({'error': 'CLAUDE.md not found'}, 404)
                return
        try:
            fp.write_text(content, encoding='utf-8')
        except Exception as e:
            self._send_json({'error': str(e)}, 500)
            return
        # Invalidate caches so graph + capabilities reload
        _graph_cache['dirty'] = True
        _cap_cache['ts'] = 0
        rel = str(fp.relative_to(BASE_DIR))
        self._send_json({'ok': True, 'path': rel})

    def _validate_file_path(self, req_path: str):
        if not req_path: return None
        req_path = req_path.strip()
        if req_path.startswith('/'):
            p = Path(req_path).resolve()
        else:
            p = (BASE_DIR / req_path).resolve()
        return p

    def _get_file(self, req_path: str):
        fp = self._validate_file_path(req_path)
        if fp is None or not fp.exists() or not fp.is_file():
            self._send_json({'error': 'not found'}, 404)
            return
        try:
            content = fp.read_text(encoding='utf-8')
        except Exception as e:
            self._send_json({'error': str(e)}, 500)
            return
        self._send_json({'path': req_path, 'content': content})

    def _put_file(self, req_path: str, content: str):
        fp = self._validate_file_path(req_path)
        if fp is None:
            self._send_json({'error': 'invalid path'}, 400)
            return
        try:
            fp.parent.mkdir(parents=True, exist_ok=True)
            fp.write_text(content, encoding='utf-8')
        except Exception as e:
            self._send_json({'error': str(e)}, 500)
            return
        self._send_json({'ok': True, 'path': req_path})

    def _serve_static(self, filename: str, ct: str):
        fp = DASHBOARD_DIR / filename
        if not fp.exists():
            self.send_error(404)
            return
        body = fp.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',   ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_report(self, name: str):
        name = os.path.basename(name)
        fp = REPORTS_DIR / name
        if not fp.exists():
            self.send_error(404)
            return
        body = fp.read_bytes()
        ct = ('text/html; charset=utf-8' if name.endswith('.html')
              else 'text/plain; charset=utf-8')
        self.send_response(200)
        self.send_header('Content-Type',   ct)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _serve_sse(self):
        self.send_response(200)
        self.send_header('Content-Type',  'text/event-stream')
        self.send_header('Cache-Control', 'no-cache')
        self.send_header('Connection',    'keep-alive')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

        q: queue.Queue = queue.Queue()
        with _sse_lock:
            _sse_clients.append(q)

        # Replay last 50 events on connect
        for ev in read_recent_events(50):
            try:
                msg = ('data: ' + json.dumps(ev, ensure_ascii=False) + '\n\n').encode()
                self.wfile.write(msg)
            except Exception:
                break

        try:
            while True:
                try:
                    msg = q.get(timeout=25)
                    self.wfile.write(msg)
                    self.wfile.flush()
                except queue.Empty:
                    self.wfile.write(b': keepalive\n\n')
                    self.wfile.flush()
        except Exception:
            pass
        finally:
            with _sse_lock:
                if q in _sse_clients:
                    _sse_clients.remove(q)


# ── Graph builder ────────────────────────────────────────────────────────────
_graph_cache: dict = {'data': None, 'dirty': True}

def _parse_sources(content: str) -> list:
    """Extract data sources table rows from a CLAUDE.md string."""
    sources = []
    m = re.search(
        r'## データソース[\s\S]*?\|[^\n]+\|\s*\n\|[-|: ]+\|\s*\n((?:\|[^\n]+\|\s*\n)+)',
        content
    )
    if not m:
        return sources
    for row in m.group(1).strip().split('\n'):
        cells = [c.strip().strip('`') for c in row.split('|') if c.strip()]
        if cells:
            sources.append({
                'path':       cells[0],
                'permission': cells[1] if len(cells) > 1 else '',
                'purpose':    cells[2] if len(cells) > 2 else '',
            })
    return sources


def build_graph() -> dict:
    """Parse agents/ directory → agent relationship graph with data sources."""
    agents_info: dict = {}
    if AGENTS_DIR.exists():
        for d in sorted(AGENTS_DIR.iterdir()):
            if not d.is_dir():
                continue
            md = d / 'CLAUDE.md'
            if not md.exists():
                continue
            try:
                content = md.read_text(encoding='utf-8', errors='replace')
            except Exception:
                content = ''
            m = re.search(r'^#\s+(.+?)(?:\s*[—\-–]\s*CLAUDE\.md)?$', content, re.MULTILINE)
            name = m.group(1).strip() if m else d.name
            agents_info[d.name] = {
                'name':    name,
                'is_lead': 'lead' in d.name.lower() and d.name.count('_') <= 2,
                'sources': _parse_sources(content),
            }

    # Group by department number prefix
    depts: dict = {}
    for folder, info in agents_info.items():
        m = re.match(r'^(\d+)', folder)
        if not m:
            continue
        num = m.group(1)
        if num not in depts:
            depts[num] = {
                'number': num,
                'label':  DEPT_LABELS.get(num, f'部門{num}'),
                'color':  DEPT_COLORS.get(num, '#888'),
                'lead':   None,
                'agents': [],
            }
        agent_entry = {'id': folder, 'name': info['name'], 'sources': info['sources']}
        if info['is_lead']:
            depts[num]['lead'] = agent_entry
        else:
            depts[num]['agents'].append(agent_entry)

    dept_list = sorted(depts.values(), key=lambda d: int(d['number']))

    # Commander name from main CLAUDE.md
    cmd_label = '司令塔エージェント'
    cmd_md = BASE_DIR / 'CLAUDE.md'
    if cmd_md.exists():
        try:
            content = cmd_md.read_text(encoding='utf-8', errors='replace')
            m = re.search(r'^#\s+([^\n]+)', content)
            if m:
                cmd_label = re.sub(r'\s*[—\-–].*', '', m.group(1)).strip()
        except Exception:
            pass

    return {
        'commander':   {'label': cmd_label},
        'departments': dept_list,
        'dept_count':  len(dept_list),
        'agent_count': sum(len(d['agents']) + (1 if d['lead'] else 0) for d in dept_list),
        'generated':   datetime.now().isoformat(),
    }

def get_graph() -> dict:
    if _graph_cache['dirty'] or not _graph_cache['data']:
        _graph_cache['data'] = build_graph()
        _graph_cache['dirty'] = False
    return _graph_cache['data']


# ── Galaxy view (Obsidian graph 風・全カスタマイズ資産の星図) ─────────────────
def _find_memory_dir() -> Path | None:
    """このリポジトリに対応する Claude Code の記憶フォルダを探す。
    導入者ごとにパスが異なるため、BASE_DIR から動的に推定する（ハードコード禁止）。"""
    try:
        if not CLAUDE_PROJECTS.exists():
            return None
        slug = re.sub(r'[\\/]', '-', str(BASE_DIR.resolve()))
        candidate = CLAUDE_PROJECTS / slug / 'memory'
        if candidate.exists():
            return candidate
        # フォールバック：フォルダ名の末尾一致で探す（プラットフォーム差の吸収）
        suffix = '-' + BASE_DIR.resolve().name
        for d in CLAUDE_PROJECTS.iterdir():
            if d.is_dir() and d.name.endswith(suffix) and (d / 'memory').exists():
                return d / 'memory'
    except Exception:
        pass
    return None

def _norm_source(p: str) -> str:
    """データソース欄のパス表記ゆれを正規化し、同一ファイルを1ノードに束ねる。"""
    p = p.strip().strip('`').strip()
    if not p:
        return ''
    if 'shared/' in p:
        return 'shared/' + p.split('shared/', 1)[1].rstrip('/')
    if 'iCloud' in p or 'obsidian' in p.lower():
        return 'obsidian/' + p.rstrip('/').split('/')[-1]
    return p.rstrip('/').split('/')[-1]

_galaxy_cache: dict = {'data': None, 'ts': 0}

def build_galaxy() -> dict:
    """司令塔・エージェント・CLAUDE.md指示セクション・共有ファイル・記憶を
    ノード＆リンク化して返す（Obsidian Graph View 風の銀河データ）。
    セットアップ未実施でも framework/ 等の骨格だけで星図になるよう設計。"""
    nodes, links = [], []
    seen: set = set()

    def add_node(nid, label, ntype, color, group=''):
        if nid in seen:
            return
        seen.add(nid)
        nodes.append({'id': nid, 'label': label, 'type': ntype,
                      'color': color, 'group': group})

    def add_link(a, b, w=1.0):
        if a in seen and b in seen and a != b:
            links.append({'s': a, 't': b, 'w': w})

    add_node('commander', '司令塔', 'commander', '#ffffff')

    # 司令塔 CLAUDE.md の ## セクション（起動判定・司令塔モードの起動手順等）
    try:
        root = (BASE_DIR / 'CLAUDE.md').read_text(encoding='utf-8', errors='replace')
        for sec in re.findall(r'^##\s+(.+?)\s*$', root, re.MULTILINE):
            nid = f'root#{sec}'
            add_node(nid, sec, 'rule', '#d9c27a')
            add_link('commander', nid, 0.6)
    except Exception:
        pass

    proto = BASE_DIR / 'shared' / '共通プロトコル.md'
    if proto.exists():
        add_node('proto', '共通プロトコル', 'rule', '#d9c27a')
        add_link('commander', 'proto', 1.2)

    # 実ファイルシステム走査：フレームワーク骨格＋導入者の生成物を星に
    WALK_DIRS = ('shared', 'reports', 'scripts', 'dashboard',
                 'framework', 'setup', 'integrations', 'examples', 'my-hub')
    SKIP_NAMES = {'.DS_Store', '__pycache__', 'logs', 'node_modules',
                  '.gitkeep', '共通プロトコル.md'}

    def walk_fs(dir_path: Path, parent_id: str):
        try:
            children = sorted(dir_path.iterdir())
        except Exception:
            return
        for child in children:
            if child.name.startswith('.') or child.name in SKIP_NAMES:
                continue
            if child.suffix in ('.log', '.pyc'):
                continue
            rel = child.relative_to(BASE_DIR).as_posix()
            nid = f'fs:{rel}'
            if child.is_dir():
                add_node(nid, child.name + '/', 'folder', '#93a0b8')
                add_link(parent_id, nid, 1.0)
                walk_fs(child, nid)
            else:
                add_node(nid, child.name, 'file', '#7d8db3')
                add_link(parent_id, nid, 1.0)

    for top in WALK_DIRS:
        p = BASE_DIR / top
        if p.exists():
            nid = f'fs:{top}'
            add_node(nid, top + '/', 'folder', '#93a0b8')
            add_link('commander', nid, 1.0)
            walk_fs(p, nid)
    if proto.exists() and 'fs:shared' in seen:
        add_link('proto', 'fs:shared', 0.4)   # プロトコルはshared/の住人

    # エージェント＋各CLAUDE.mdの##セクション＋データソース（導入者のセットアップ後に充実）
    if AGENTS_DIR.exists():
        for d in sorted(AGENTS_DIR.iterdir()):
            if not d.is_dir():
                continue
            a = _parse_agent(d)
            if not a:
                continue
            add_node(d.name, a['name'], 'agent', a['color'], d.name)
            add_link('commander', d.name, 2.0)
            if proto.exists():
                add_link(d.name, 'proto', 0.3)
            try:
                content = (d / 'CLAUDE.md').read_text(encoding='utf-8', errors='replace')
                for sec in re.findall(r'^##\s+(.+?)\s*$', content, re.MULTILINE):
                    nid = f'{d.name}#{sec}'
                    add_node(nid, sec, 'section', a['color'], d.name)
                    add_link(d.name, nid, 0.5)
            except Exception:
                pass
            for src in a['sources']:
                norm = _norm_source(src.get('path', ''))
                if not norm:
                    continue
                # 実在するファイル/フォルダなら実FSノードへ接続（銀河の幹線）
                if norm.startswith('shared/') and f'fs:{norm}' in seen:
                    add_link(d.name, f'fs:{norm}', 1.0)
                    continue
                fid = f'ext:{norm}'
                add_node(fid, norm.rstrip('/').split('/')[-1], 'file', '#7d8db3')
                add_link(d.name, fid, 1.0)

    # 記憶ファイル（[[wikilink]] も実リンク化・導入者ごとにパスを動的推定）
    memory_dir = _find_memory_dir()
    if memory_dir:
        mems = [f for f in sorted(memory_dir.glob('*.md')) if f.name != 'MEMORY.md']
        for f in mems:
            add_node(f'mem:{f.stem}', f.stem, 'memory', '#a78bfa')
            add_link('commander', f'mem:{f.stem}', 0.3)
        for f in mems:
            try:
                text = f.read_text(encoding='utf-8', errors='replace')
            except Exception:
                continue
            for target in re.findall(r'\[\[([^\]\|#]+)', text):
                tid = f'mem:{target.strip()}'
                if tid in seen:
                    add_link(f'mem:{f.stem}', tid, 0.8)

    deg: dict = {}
    for l in links:
        deg[l['s']] = deg.get(l['s'], 0) + 1
        deg[l['t']] = deg.get(l['t'], 0) + 1
    for n in nodes:
        n['deg'] = deg.get(n['id'], 0)

    return {'nodes': nodes, 'links': links,
            'generated': datetime.now().isoformat()}

def get_galaxy() -> dict:
    now = time.time()
    if not _galaxy_cache['data'] or now - _galaxy_cache['ts'] > 30:
        _galaxy_cache['data'] = build_galaxy()
        _galaxy_cache['ts'] = now
    return _galaxy_cache['data']


# ── Config file watcher ───────────────────────────────────────────────────────
def _watched_files() -> list:
    files = [BASE_DIR / 'CLAUDE.md']
    if AGENTS_DIR.exists():
        for d in AGENTS_DIR.iterdir():
            if d.is_dir():
                f = d / 'CLAUDE.md'
                if f.exists():
                    files.append(f)
    return files

def _watch_configs():
    """Poll CLAUDE.md files for changes; broadcast config_changed via SSE."""
    mtimes: dict = {}
    # Seed initial mtimes silently
    for f in _watched_files():
        try:
            mtimes[str(f)] = f.stat().st_mtime
        except Exception:
            pass
    while True:
        time.sleep(2)
        changed = []
        for f in _watched_files():
            try:
                mtime = f.stat().st_mtime
                prev  = mtimes.get(str(f))
                if prev is None:
                    mtimes[str(f)] = mtime
                    changed.append(f.name)
                elif prev != mtime:
                    mtimes[str(f)] = mtime
                    changed.append(f.name)
            except Exception:
                pass
        if changed:
            _graph_cache['dirty'] = True
            broadcast_sse({
                'event': 'config_changed',
                'ts':    datetime.now().isoformat(),
                'files': changed,
            })


# ── Entry point ──────────────────────────────────────────────────────────────
if __name__ == '__main__':
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765

    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    LOG_FILE.touch(exist_ok=True)
    _load_labels()

    threading.Thread(target=_tail_log,      daemon=True).start()
    threading.Thread(target=_watch_configs, daemon=True).start()

    ThreadingHTTPServer.allow_reuse_address = True
    server = ThreadingHTTPServer(('localhost', port), Handler)
    print(f'Agent Hub Dashboard → http://localhost:{port}')
    print('Ctrl+C to stop.')
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print('\nStopped.')
