import subprocess, json, os, re, urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed

BASE = "https://rxnav.nlm.nih.gov/REST"
CKPT = "out/rxnorm.jsonl"

drugs = {d["ddinter_id"]: d["name"] for d in json.load(open("out/ddi_knowledge_base_enriched.json"))["drugs"]}

done = {}
if os.path.exists(CKPT):
    for line in open(CKPT):
        try:
            r = json.loads(line); done[r["ddinter_id"]] = r
        except Exception:
            pass

def curl_json(url):
    out = subprocess.run(["curl", "-s", "--max-time", "30", url], capture_output=True, text=True).stdout
    return json.loads(out) if out.strip() else {}

def strip_qual(name):
    # drop trailing parenthetical dose-form qualifiers, e.g. "Betamethasone (topical)"
    return re.sub(r"\s*\([^)]*\)\s*$", "", name).strip()

def exact(name):
    d = curl_json(f"{BASE}/rxcui.json?name={urllib.parse.quote(name)}&search=1")
    ids = (d.get("idGroup") or {}).get("rxnormId") or []
    return ids[0] if ids else None

def approximate(name):
    d = curl_json(f"{BASE}/approximateTerm.json?term={urllib.parse.quote(name)}&maxEntries=1")
    cands = (d.get("approximateGroup") or {}).get("candidate") or []
    if cands:
        c = cands[0]
        return c.get("rxcui"), c.get("name")
    return None, None

def rxname(rxcui):
    d = curl_json(f"{BASE}/rxcui/{rxcui}/property.json?propName=RxNorm%20Name")
    props = (d.get("propConceptGroup") or {}).get("propConcept") or []
    return props[0]["propValue"] if props else None

def resolve(did):
    name = drugs[did]
    rxcui = exact(name); mt = "exact"
    if not rxcui:
        s = strip_qual(name)
        if s != name:
            rxcui = exact(s)
            if rxcui: mt = "exact_stripped"
    approx_name = None
    if not rxcui:
        rxcui, approx_name = approximate(name)
        if rxcui:
            mt = "approximate"
    return {"ddinter_id": did, "name": name, "rxcui": rxcui,
            "rxnorm_name": (approx_name if mt == "approximate" else rxname(rxcui)) if rxcui else None,
            "match_type": mt if rxcui else None}

todo = [d for d in drugs if d not in done]
print(f"to resolve: {len(todo)} ({len(done)} cached)")
fh = open(CKPT, "a")
n = 0
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(resolve, d): d for d in todo}
    for fut in as_completed(futs):
        try:
            r = fut.result()
        except Exception:
            continue
        fh.write(json.dumps(r, ensure_ascii=False) + "\n"); n += 1
        if n % 300 == 0:
            fh.flush(); print(f"  {n}/{len(todo)}")
fh.flush(); fh.close()

# report
allr = list(done.values())
for line in open(CKPT):
    try:
        allr.append(json.loads(line))
    except Exception:
        pass
uniq = {r["ddinter_id"]: r for r in allr}
matched = sum(1 for r in uniq.values() if r["rxcui"])
by = {}
for r in uniq.values():
    by[r["match_type"]] = by.get(r["match_type"], 0) + 1
print("RESOLVED", matched, "/", len(uniq))
print("by match_type:", by)
