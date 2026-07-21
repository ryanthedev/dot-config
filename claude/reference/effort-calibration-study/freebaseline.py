#!/usr/bin/env python3
"""Free a-priori baseline: can repo / task-type / request-length predict effort?
Leave-one-out median predictors, pairwise ranking + Spearman, session-clustered bootstrap CIs.
All predictors are a-priori-knowable (no leakage). Targets: active_min, tool_calls."""
import json, os, random, statistics as st
random.seed(7)
HERE=os.path.dirname(__file__)
D=json.load(open(os.path.join(HERE,"enriched.json")))

def rankv(xs):
    order=sorted(range(len(xs)),key=lambda i:xs[i]); r=[0.0]*len(xs); i=0
    while i<len(xs):
        j=i
        while j+1<len(xs) and xs[order[j+1]]==xs[order[i]]: j+=1
        for k in range(i,j+1): r[order[k]]=(i+j)/2+1
        i=j+1
    return r
def pearson(x,y):
    n=len(x); mx=sum(x)/n; my=sum(y)/n
    num=sum((a-mx)*(b-my) for a,b in zip(x,y))
    dx=sum((a-mx)**2 for a in x)**.5; dy=sum((b-my)**2 for b in y)**.5
    return num/(dx*dy) if dx and dy else float('nan')
def spearman(x,y): return pearson(rankv(x),rankv(y))
def pairwise(scores,actual):
    c=d=0; n=len(scores)
    for i in range(n):
        for j in range(i+1,n):
            da=actual[i]-actual[j]; ds=scores[i]-scores[j]
            if da==0 or ds==0: continue
            c+= (da>0)==(ds>0); d+= (da>0)!=(ds>0)
    return c/(c+d) if (c+d) else float('nan')
def boot_pairwise(scores,actual,B=2000):
    n=len(scores); vals=[]
    for _ in range(B):
        idx=[random.randrange(n) for _ in range(n)]  # cluster unit = session
        s=[scores[i] for i in idx]; a=[actual[i] for i in idx]
        v=pairwise(s,a)
        if v==v: vals.append(v)
    vals.sort()
    return vals[int(.025*len(vals))], vals[int(.975*len(vals))]

def loo_group_median(recs, key, tgt, min_n=3):
    """score each rec = median target of OTHER recs sharing its key; fallback global median."""
    gmed=st.median([r[tgt] for r in recs])
    groups={}
    for r in recs: groups.setdefault(r[key],[]).append(r[tgt])
    scores=[]
    for r in recs:
        vals=[v for v in groups[r[key]]]
        vals2=list(vals); vals2.remove(r[tgt])
        if len(vals2)>=min_n-1 and len(groups[r[key]])>=min_n:
            scores.append(st.median(vals2))
        else:
            scores.append(gmed)
    return scores

def report(recs, tgt, label):
    actual=[r[tgt] for r in recs]
    print(f"\n### target={tgt}  ({label}, n={len(recs)})   [ranking baseline = 50% chance]")
    print(f"{'predictor':<22}{'pairwise':>9}{'95% CI':>16}{'spearman':>10}")
    preds={
        "per-repo median (LOO)": loo_group_median(recs,"repo",tgt),
        "per-type median (LOO)": loo_group_median(recs,"type",tgt),
        "request words":         [r["req_words"] for r in recs],
        "lowinfo flag (0/1)":    [0 if r["lowinfo"] else 1 for r in recs],
    }
    for name,sc in preds.items():
        lo,hi=boot_pairwise(sc,actual)
        print(f"{name:<22}{pairwise(sc,actual)*100:>8.0f}%   [{lo*100:>4.0f}%,{hi*100:>4.0f}%]{spearman(sc,actual):>10.2f}")

# --- ranking analysis: full + low-turn stratum ---
for tgt in ["active_min","tool_calls"]:
    report(D, tgt, "ALL")
low=[r for r in D if r["human_turns"]<=3]
for tgt in ["active_min","tool_calls"]:
    report(low, tgt, "low-turn <=3")

# --- point-error: does repo/type median beat global median? (active_min) ---
def mape(a,p,mean=False):
    e=[abs(pp-aa)/max(aa,.1) for aa,pp in zip(a,p)]
    return sum(e)/len(e) if mean else st.median(e)
a=[r["active_min"] for r in D]; gmed=st.median(a)
print("\n### point-error active_min (all)  MAPE median / mean")
print(f"null global median : {mape(a,[gmed]*len(a))*100:>5.0f}% / {mape(a,[gmed]*len(a),1)*100:>5.0f}%")
print(f"per-repo LOO median: {mape(a,loo_group_median(D,'repo','active_min'))*100:>5.0f}% / {mape(a,loo_group_median(D,'repo','active_min'),1)*100:>5.0f}%")
print(f"per-type LOO median: {mape(a,loo_group_median(D,'type','active_min'))*100:>5.0f}% / {mape(a,loo_group_median(D,'type','active_min'),1)*100:>5.0f}%")

# --- calibration table (Exp 2) ---
from collections import Counter
def pct(v,q):
    v=sorted(v); i=min(len(v)-1,int(q*len(v))); return v[i]
print("\n### CALIBRATION: per-type session percentiles (types with n>=10)")
print(f"{'type':<16}{'n':>4}{'active_min p10/50/90':>26}{'tool_calls p10/50/90':>24}")
by={}
for r in D: by.setdefault(r["type"],[]).append(r)
type_meds={}
for t,rs in sorted(by.items(),key=lambda kv:-len(kv[1])):
    if len(rs)<10: continue
    am=[r["active_min"] for r in rs]; tc=[r["tool_calls"] for r in rs]
    type_meds[t]=st.median(am)
    print(f"{t:<16}{len(rs):>4}   {pct(am,.1):>5.1f}/{st.median(am):>5.1f}/{pct(am,.9):>6.1f}      {pct(tc,.1):>4.0f}/{st.median(tc):>4.0f}/{pct(tc,.9):>5.0f}")
if type_meds:
    r=max(type_meds.values())/min(type_meds.values())
    print(f"type median active_min spread: {min(type_meds.values()):.1f} -> {max(type_meds.values()):.1f} min  (max/min = {r:.1f}x; pre-declared 'separates' if >=2.0x)")

print("\n### CALIBRATION: per-repo session percentiles (repos with n>=10)")
print(f"{'repo':<18}{'n':>4}{'active_min p10/50/90':>26}")
byr={}
for r in D: byr.setdefault(r["repo"],[]).append(r)
for repo,rs in sorted(byr.items(),key=lambda kv:-len(kv[1])):
    if len(rs)<10: continue
    am=[r["active_min"] for r in rs]
    print(f"{repo:<18}{len(rs):>4}   {pct(am,.1):>5.1f}/{st.median(am):>5.1f}/{pct(am,.9):>6.1f}")

print("\n### persistence effect: active_min median, all vs low-turn(<=3), by type(n>=10)")
for t,rs in sorted(by.items(),key=lambda kv:-len(kv[1])):
    if len(rs)<10: continue
    lo=[r["active_min"] for r in rs if r["human_turns"]<=3]
    print(f"{t:<16} all_med={st.median([r['active_min'] for r in rs]):>5.1f}  low-turn_med={st.median(lo) if lo else float('nan'):>5.1f}  (low-turn n={len(lo)})")
