import json, subprocess, time, re, urllib.parse

RX = "https://rxnav.nlm.nih.gov/REST"

def curl(url):
    return subprocess.run(["curl","-s","--max-time","30",url], capture_output=True, text=True).stdout

def jget(url):
    o = curl(url)
    try: return json.loads(o) if o.strip() else {}
    except Exception: return {}

def status_name(rx):
    h = jget(f"{RX}/rxcui/{rx}/historystatus.json").get("rxcuiStatusHistory",{})
    return h.get("metaData",{}).get("status"), (h.get("attributes") or {}).get("name")

def exact_ids(name):
    d = jget(f"{RX}/rxcui.json?name={urllib.parse.quote(name)}&search=1")
    return (d.get("idGroup") or {}).get("rxnormId") or []

def approx_ids(name, n=8):
    d = jget(f"{RX}/approximateTerm.json?term={urllib.parse.quote(name)}&maxEntries={n}")
    return [c.get("rxcui") for c in ((d.get("approximateGroup") or {}).get("candidate") or [])]

def to_IN(rx):
    d = jget(f"{RX}/rxcui/{rx}/related.json?tty=IN")
    for g in (d.get("relatedGroup") or {}).get("conceptGroup") or []:
        for p in (g.get("conceptProperties") or []):
            return p["rxcui"], p.get("name")
    return None, None

def clean(name):
    return re.sub(r"\s*\([^)]*\)\s*", " ", name).strip()

# the 32 to remap: recompute from review file (divergent approximate matches)
drugs = {x["name"]: x for x in json.load(open("out/ddi_knowledge_base_enriched.json"))["drugs"]}
appr = [x for x in json.load(open("out/rxcui_review.json"))["residual_review"] if "approximate" in x["reason"]]
def norm(s): return re.sub(r"[^a-z0-9]","",(s or "").lower())
targets = []
for x in appr:
    d = drugs[x["name"]]; rn = d.get("rxnorm_name") or ""
    if not (norm(d["name"])==norm(rn) or (norm(rn) and (norm(rn) in norm(d["name"]) or norm(d["name"]) in norm(rn)))):
        targets.append(d["name"])

remap = {}
for nm in targets:
    cand = exact_ids(clean(nm)) or exact_ids(nm) or approx_ids(clean(nm))
    chosen = None
    for c in cand[:8]:
        st, _ = status_name(c)
        if st == "Active":
            chosen = c; break
        time.sleep(0.15)
    if chosen:
        inrx, innm = to_IN(chosen)
        final = inrx or chosen
        st, fname = status_name(final)
        remap[nm] = {"rxcui": final, "rxnorm_name": fname, "status": st, "via": "IN" if inrx else "concept"}
    else:
        remap[nm] = {"rxcui": None, "rxnorm_name": None, "status": "no_current_match"}
    r = remap[nm]
    print(f"  {nm:46} -> {r['rxcui']}  {r.get('rxnorm_name')}  [{r['status']}]")
    time.sleep(0.2)

json.dump(remap, open("out/notcurrent_remap.json","w"), ensure_ascii=False, indent=2)
resolved = sum(1 for r in remap.values() if r["rxcui"])
print(f"\nremapped to current: {resolved}/{len(remap)}  |  no current match: {len(remap)-resolved}")
