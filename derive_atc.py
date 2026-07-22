import subprocess, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

RX = "https://rxnav.nlm.nih.gov/REST"
CACHE = "out/atc_cache.jsonl"

drugs = json.load(open("out/ddi_knowledge_base_enriched.json"))["drugs"]
rxcuis = sorted({d["rxcui"] for d in drugs if d.get("rxcui")})

done = {}
if os.path.exists(CACHE):
    for line in open(CACHE):
        try:
            r = json.loads(line); done[r["rxcui"]] = r["atc"]
        except Exception:
            pass

def atc_for(rx):
    out = subprocess.run(["curl","-s","--max-time","30",
        f"{RX}/rxclass/class/byRxcui.json?rxcui={rx}&relaSource=ATC"], capture_output=True, text=True).stdout
    codes = []
    try:
        for info in (json.loads(out).get("rxclassDrugInfoList") or {}).get("rxclassDrugInfo") or []:
            c = (info.get("rxclassMinConceptItem") or {}).get("classId")
            if c and c not in codes:
                codes.append(c)
    except Exception:
        pass
    return rx, codes

todo = [r for r in rxcuis if r not in done]
print(f"ATC to derive: {len(todo)} ({len(done)} cached) of {len(rxcuis)}")
fh = open(CACHE, "a"); n = 0
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(atc_for, r): r for r in todo}
    for fut in as_completed(futs):
        rx, codes = fut.result()
        done[rx] = codes
        fh.write(json.dumps({"rxcui": rx, "atc": codes}) + "\n"); n += 1
        if n % 400 == 0:
            fh.flush(); print(f"  {n}/{len(todo)}")
fh.flush(); fh.close()
withatc = sum(1 for r in rxcuis if done.get(r))
print(f"DONE. rxcuis with >=1 ATC: {withatc}/{len(rxcuis)}")
