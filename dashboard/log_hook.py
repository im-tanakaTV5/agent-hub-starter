#!/usr/bin/env python3
"""
Claude Code & Antigravity CLI hook → agent-hub dashboard log writer.
Receives JSON on stdin, appends a compact entry to events.jsonl.
Never raises exceptions — must not block execution.

Identity capture:
- `agent_id`        : present ONLY for sub-agent tool calls. Empty = 司令塔 (main session).
- `child_agent_id`  : on an `Agent` post_tool, the spawned sub-agent's id (parsed from the
                      tool result's "agentId: X"). Lets the dashboard map agent_id → 部門
                      via the dispatch prompt.
"""
import sys, json, datetime, re
from pathlib import Path

# このスクリプト自身の場所からログパスを導出する（どこに置いても動く）
LOG = Path(__file__).resolve().parent / 'logs' / 'events.jsonl'


def truncate(v, n=400):
    if isinstance(v, str):
        return v[:n] + ('…' if len(v) > n else '')
    if isinstance(v, dict):
        return {k: truncate(vv, n) for k, vv in list(v.items())[:8]}
    if isinstance(v, list):
        return [truncate(i, n) for i in v[:5]]
    return v


def main():
    event_type = sys.argv[1] if len(sys.argv) > 1 else 'unknown'

    try:
        raw = sys.stdin.read()
        data = json.loads(raw) if raw.strip() else {}
    except Exception:
        data = {}

    # Extract fields with fallback for different agent formats
    tool_name = data.get("tool_name") or data.get("tool") or ""
    tool_input = data.get("tool_input") or data.get("input") or {}
    session_id = data.get("session_id") or data.get("sessionId") or ""
    agent_id = data.get("agent_id") or data.get("agentId") or ""

    # Antigravity CLI payload shape: tool info nested under toolCall.args
    # e.g. .toolCall.args.ToolName / .toolCall.args.CommandLine
    if not tool_name and isinstance(data.get("toolCall"), dict):
        tc = data["toolCall"]
        args = tc.get("args") if isinstance(tc.get("args"), dict) else {}
        tool_name = args.get("ToolName") or tc.get("name") or tc.get("tool") or ""
        if not tool_input:
            tool_input = args

    # Estimate tokens from response length before truncating
    token_estimate = None
    response = data.get('tool_response') or data.get('response')
    if response is not None:
        s = response if isinstance(response, str) else json.dumps(response)
        token_estimate = max(1, len(s) // 4)

    entry = {
        "ts":         datetime.datetime.now().isoformat(),
        "event":      event_type,
        "session_id": str(session_id)[:16],
        "agent_id":   str(agent_id),
        "tool_name":  str(tool_name),
        "tool_input": truncate(tool_input),
    }

    # Link parent → child: extract the spawned sub-agent's id from an Agent result.
    # (Claude Code: "Agent" / Antigravity CLI: "start_subagent")
    if tool_name in ("Agent", "start_subagent") and event_type == "post_tool" and response is not None:
        try:
            s = response if isinstance(response, str) else json.dumps(response, ensure_ascii=False)
            m = re.search(r'agentId["\']?\s*[:=]\s*["\']?([0-9a-fA-F]{10,})', s)
            if m:
                entry["child_agent_id"] = m.group(1)
        except Exception:
            pass

    if token_estimate is not None:
        entry["token_estimate"] = token_estimate

    if event_type == "stop":
        entry["transcript_path"] = data.get("transcript_path", "")

    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(LOG, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
    except Exception:
        pass  # Never block execution

    # Antigravity PreToolUse hook expects a decision returned via stdout
    if event_type == 'pre_tool':
        print(json.dumps({"decision": "allow"}))


if __name__ == '__main__':
    main()
