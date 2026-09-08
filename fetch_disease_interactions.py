"""
fetch_disease_interactions.py — fetch each drug's drug-disease interactions from DDInter 2.0.

Produces src/disease_interactions.jsonl (one line per drug: its DDInter id and the
disease rows DDInter publishes for it), a committed build input that build_kb.py
joins into the knowledge base's disease_interactions table. Needs network.

Why this table matters: DDInter rates some clinically real pairs "Unknown" as
drug-drug rows while carrying the knowledge as drug-disease rows. Stavudine +
metformin is the canonical case — the pairwise row has no text, but stavudine's
"Liver Diseases" row names lactic acidosis and metformin's "Acidosis, Lactic" row
is Major. Ingesting this table lets query_kb.py derive that finding, labelled as
a derivation rather than a DDInter pairwise rating.

Endpoint (the checker page's own table source, a server-side DataTables POST):
  POST https://ddinter2.scbdd.com/server/interact-with-dis/{ddinter_id}/
       draw=1 start=0 length=500 severity=
  -> {"recordsTotal": n, "data": [{"interaction_id", "level", "diseaseName", "text", "references"}]}
Level scale is DDInter's usual: 3 Major, 2 Moderate, 1 Minor, 0 Unknown.

Resumable: drugs already present in the output file are skipped, so an interrupted
run picks up where it stopped. Failed requests are not recorded, so a rerun retries
them. The file is rewritten in stable drug order at the end.
"""
import json, os, subprocess, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed

URL = "https://ddinter2.scbdd.com/server/interact-with-dis/{}/"
OUT = "src/disease_interactions.jsonl"
SEVMAP = {"3": "Major", "2": "Moderate", "1": "Minor", "0": "Unknown"}
PAGE = 500
WORKERS = 4          # polite to an academic server; ~2,300 requests total

drugs = [json.loads(l) for l in open("src/drugs.jsonl")]
order = [d["id"] for d in drugs]

done = {}
if os.path.exists(OUT):
    for l in open(OUT):
        r = json.loads(l); done[r["ddinter_id"]] = r

def page(did, start):
    out = subprocess.run(["curl", "-s", "--max-time", "40", "-X", "POST",
        "-d", "draw=1", "-d", f"start={start}", "-d", f"length={PAGE}", "-d", "severity=",
        URL.format(did)], capture_output=True, text=True).stdout
    return json.loads(out)          # raises on the server's non-JSON error text

def fetch(did):
    rows, start, total = [], 0, None
    while total is None or start < total:
        d = page(did, start)
        total = int(d["recordsTotal"])
        for r in d["data"]:
            refs = [x.strip() for x in (r.get("references") or "").split("|") if x.strip()]
            rows.append({"interaction_id": r["interaction_id"], "disease": r["diseaseName"].strip(),
                         "severity": SEVMAP.get(str(r["level"]), "Unknown"),
                         "text": (r.get("text") or "").strip() or None, "references": refs})
        start += PAGE
    rows.sort(key=lambda r: (r["disease"], r["interaction_id"]))
    return {"ddinter_id": did, "rows": rows}

todo = [d for d in order if d not in done]
print(f"{len(done)} drugs already fetched; fetching {len(todo)}")
failed = []
with ThreadPoolExecutor(max_workers=WORKERS) as ex, open(OUT, "a") as f:
    futs = {ex.submit(fetch, d): d for d in todo}
    n = 0
    for fut in as_completed(futs):
        did = futs[fut]
        try:
            rec = fut.result()
        except Exception as e:
            failed.append(did); continue
        done[did] = rec
        f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()   # progress survives interruption
        n += 1
        if n % 200 == 0:
            print(f"  {n}/{len(todo)}", flush=True)

with open(OUT, "w") as f:                     # stable drug order for a clean diff
    for did in order:
        if did in done:
            f.write(json.dumps(done[did], ensure_ascii=False) + "\n")

rows = sum(len(r["rows"]) for r in done.values())
withrows = sum(1 for r in done.values() if r["rows"])
sev = {}
for r in done.values():
    for x in r["rows"]:
        sev[x["severity"]] = sev.get(x["severity"], 0) + 1
print(f"wrote {OUT}: {len(done)}/{len(order)} drugs | {withrows} with >=1 disease row | {rows} rows | severity {sev}")
if failed:
    print(f"FAILED {len(failed)} drugs (rerun to retry): {failed[:10]}")
    sys.exit(1)
