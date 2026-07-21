#!/usr/bin/env python3
"""Mine ~/.claude/projects/*.jsonl into a per-session feature table.
Read-only. Streams line-by-line to stay memory-flat over 2.4G."""
import os, json, glob, csv, sys
from datetime import datetime

ROOT = os.path.expanduser("~/.claude/projects")
OUT = os.path.join(os.path.dirname(__file__), "sessions.csv")
IDLE_CAP = 120.0   # seconds; gaps longer than this are treated as human-idle and clipped
IDLE_BREAK = 300.0 # gaps longer than this counted as an idle break

def parse_ts(s):
    if not s: return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None

def has_tool_result(msg):
    c = msg.get("content")
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_result":
                return True
    return False

def count_tool_uses(msg):
    c = msg.get("content")
    n = 0
    if isinstance(c, list):
        for b in c:
            if isinstance(b, dict) and b.get("type") == "tool_use":
                n += 1
    return n

rows = []
files = glob.glob(os.path.join(ROOT, "*", "*.jsonl"))
for fp in files:
    ts_list = []
    n_user_turns = n_assistant = n_tool_calls = 0
    out_tokens = 0
    models = set()
    entrypoint = ""
    version = ""
    branch = ""
    cwd = ""
    has_sidechain = False
    try:
        with open(fp, "r", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line: continue
                try:
                    o = json.loads(line)
                except Exception:
                    continue
                t = o.get("type")
                ts = parse_ts(o.get("timestamp"))
                if ts: ts_list.append(ts)
                if o.get("isSidechain"): has_sidechain = True
                if o.get("entrypoint"): entrypoint = o.get("entrypoint")
                if o.get("version"): version = o.get("version")
                if o.get("gitBranch"): branch = o.get("gitBranch")
                if o.get("cwd"): cwd = o.get("cwd")
                msg = o.get("message") or {}
                if t == "assistant":
                    n_assistant += 1
                    if msg.get("model"): models.add(msg["model"])
                    u = msg.get("usage") or {}
                    out_tokens += int(u.get("output_tokens") or 0)
                    n_tool_calls += count_tool_uses(msg)
                elif t == "user":
                    if o.get("isMeta"): continue
                    if has_tool_result(msg): continue  # tool response, not a human turn
                    n_user_turns += 1
    except Exception:
        continue
    if len(ts_list) < 2:
        continue
    ts_list.sort()
    span = ts_list[-1] - ts_list[0]
    active = 0.0
    idle_breaks = 0
    for a, b in zip(ts_list, ts_list[1:]):
        g = b - a
        if g > IDLE_BREAK: idle_breaks += 1
        active += min(g, IDLE_CAP)
    rows.append({
        "file": os.path.basename(fp),
        "project": os.path.basename(os.path.dirname(fp)),
        "cwd": cwd,
        "branch": branch,
        "entrypoint": entrypoint,
        "version": version,
        "sidechain": int(has_sidechain),
        "user_turns": n_user_turns,
        "assistant_msgs": n_assistant,
        "tool_calls": n_tool_calls,
        "out_tokens": out_tokens,
        "models": "|".join(sorted(models)),
        "span_sec": round(span, 1),
        "active_sec": round(active, 1),
        "idle_breaks": idle_breaks,
    })

with open(OUT, "w", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()))
    w.writeheader()
    w.writerows(rows)

print(f"files scanned: {len(files)}")
print(f"sessions with >=2 timestamps: {len(rows)}")
print(f"wrote: {OUT}")
