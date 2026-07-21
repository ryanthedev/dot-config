#!/usr/bin/env python3
"""Enrich the clean cli set with opening request, task-type (rules), repo key, files_touched.
Joins deterministic actuals from sessions.csv. No LLM, no leakage: all features a-priori-knowable."""
import os, json, csv, re
HERE=os.path.dirname(__file__)
ROOT=os.path.expanduser("~/.claude/projects")
CSV=os.path.join(HERE,"sessions.csv")
EDIT_TOOLS={"Edit","Write","MultiEdit","NotebookEdit"}

def msg_text(msg):
    c=msg.get("content")
    if isinstance(c,str): return c
    if isinstance(c,list):
        return "\n".join(b.get("text","") for b in c if isinstance(b,dict) and b.get("type")=="text")
    return ""
def has_tool_result(msg):
    c=msg.get("content")
    return isinstance(c,list) and any(isinstance(b,dict) and b.get("type")=="tool_result" for b in c)

def opening_and_files(fp):
    opening=None; files=set()
    with open(fp,errors="replace") as fh:
        for line in fh:
            line=line.strip()
            if not line: continue
            try: o=json.loads(line)
            except Exception: continue
            t=o.get("type"); msg=o.get("message") or {}
            if t=="assistant" and isinstance(msg.get("content"),list):
                for b in msg["content"]:
                    if isinstance(b,dict) and b.get("type")=="tool_use" and b.get("name") in EDIT_TOOLS:
                        inp=b.get("input") or {}
                        f=inp.get("file_path") or inp.get("notebook_path")
                        if f: files.add(f)
            elif t=="user" and not o.get("isMeta") and not has_tool_result(msg) and opening is None:
                txt=msg_text(msg).strip()
                if txt: opening=txt
    return opening, len(files)

PTR=re.compile(r'(pick back up|previous session|prev session|get up to speed|necro|nerco|checkout |go through the previous|:\d\b)', re.I)
def is_lowinfo(req):
    r=req.strip()
    if len(r)<15: return True
    if r.startswith('<command') or r.startswith('/'): return True
    if PTR.search(r): return True
    return False

def task_type(req):
    r=req.lower().strip()
    if r.startswith('<command') or r.startswith('/'): return "command"
    if PTR.search(r): return "resume-pointer"
    def has(*ws): return any(w in r for w in ws)
    if has('refactor','clean up','reorganize','restructure','redesign','rename'): return "refactor"
    if has('why',' bug','debug',' fix ','broken','not work','doesn\'t work','fail','error','wtf','turd'): return "debug"
    if has(' add ','create','implement','build a','make a',' new ','set up','setup','scaffold'): return "feature-build"
    if has('config','settings','install','disable','enable','sip','yabai','env '): return "config"
    if has('understand','explain','how ','what ','breakdown','look at','curious','do you know','tell me','which','see if','?'): return "research-qa"
    return "other"

def repo_key(cwd):
    parts=cwd.rstrip('/').split('/')
    if 'repos' in parts:
        i=parts.index('repos')
        if i+1<len(parts): return parts[i+1]
    if 'worktrees' in cwd: return "(worktree)"
    return parts[-1] if parts else cwd

rows=[r for r in csv.DictReader(open(CSV))
      if r["entrypoint"]=="cli" and int(r["assistant_msgs"])>0 and int(r["user_turns"])>=2
      and float(r["active_sec"])>30 and "necro" not in r["cwd"].lower() and "/t/" not in r["cwd"].lower()]

out=[]
for r in rows:
    fp=os.path.join(ROOT,r["project"],r["file"])
    if not os.path.exists(fp): continue
    opening,files=opening_and_files(fp)
    if not opening: continue
    out.append({
        "id": r["file"][:8],
        "repo": repo_key(r["cwd"]),
        "type": task_type(opening),
        "lowinfo": is_lowinfo(opening),
        "req_words": len(opening.split()),
        "tool_calls": int(r["tool_calls"]),
        "files_touched": files,
        "active_min": round(float(r["active_sec"])/60,2),
        "human_turns": int(r["user_turns"]),
        "out_tokens": int(r["out_tokens"]),
        "models": r["models"],
    })
json.dump(out,open(os.path.join(HERE,"enriched.json"),"w"),indent=2)

from collections import Counter
print(f"clean cli sessions enriched: {len(out)}")
print("by type:", dict(Counter(x["type"] for x in out)))
print("lowinfo:", sum(x["lowinfo"] for x in out), "/", len(out))
print("repos with >=3 sessions:", sum(1 for k,v in Counter(x["repo"] for x in out).items() if v>=3))
print("top repos:", Counter(x["repo"] for x in out).most_common(8))
