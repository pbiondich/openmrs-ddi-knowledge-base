"""
derive_atc.py — (re)derive each drug's ATC codes from RxNorm, at level-5 granularity.

Produces src/atc_cache.jsonl (rxcui -> [ATC codes]), one of the committed build
inputs that build_kb.py joins into the drugs table. Run this to refresh ATC when
the drug set changes; it needs network (RxNav).

IMPORTANT — level-5, not level-4. The module's DrugSafetyValidator and order
matcher key on RxNorm level-5 *substance* codes (7 chars, e.g. C09AA03). An
earlier version used RxClass `class/byRxcui?relaSource=ATC`, which returns level-4
*subgroup* codes (5 chars, e.g. C09AA); that mismatch made the same-drug skip miss
and fired a false duplicate-therapy warning on the patient's own drug. The correct
source is the RxNorm ATC *property* (`property.json?propName=ATC`), which carries
the level-5 codes. build_kb.py enforces the level-5 invariant, so a regression here
fails the build rather than shipping quietly.
"""
import subprocess, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

RX = "https://rxnav.nlm.nih.gov/REST"
CACHE = "src/atc_cache.jsonl"
ATC_LEVEL5_LEN = 7

rxcuis = sorted({d["rxcui"] for d in json.load(open("out/ddi_knowledge_base.json"))["drugs"] if d.get("rxcui")})

def atc5(rx):
    out = subprocess.run(["curl", "-s", "--max-time", "30",
        f"{RX}/rxcui/{rx}/property.json?propName=ATC"], capture_output=True, text=True).stdout
    codes = []
    try:
        for p in (json.loads(out).get("propConceptGroup") or {}).get("propConcept") or []:
            c = p.get("propValue")
            if c and len(c) == ATC_LEVEL5_LEN and c not in codes:   # level-5 substance code only
                codes.append(c)
    except Exception:
        pass
    return rx, codes

result = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(atc5, r): r for r in rxcuis}
    n = 0
    for fut in as_completed(futs):
        rx, codes = fut.result(); result[rx] = codes; n += 1
        if n % 400 == 0:
            print(f"  {n}/{len(rxcuis)}")

with open(CACHE, "w") as f:
    for rx in rxcuis:                       # stable rxcui order
        f.write(json.dumps({"rxcui": rx, "atc": result.get(rx, [])}) + "\n")

lens = {}
for codes in result.values():
    for c in codes:
        lens[len(c)] = lens.get(len(c), 0) + 1
withatc = sum(1 for r in rxcuis if result.get(r))
print(f"wrote {CACHE}: {withatc}/{len(rxcuis)} rxcuis with >=1 ATC | code-length dist: {lens}")
assert set(lens) <= {ATC_LEVEL5_LEN}, f"ATC codes must be level-5 ({ATC_LEVEL5_LEN} chars); got {lens}"
