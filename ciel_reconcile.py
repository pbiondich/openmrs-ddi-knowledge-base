import subprocess, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

RXBASE = "https://rxnav.nlm.nih.gov/REST"
CACHE = "out/ingredient_cache.jsonl"

kb = json.load(open("out/ddi_knowledge_base_enriched.json"))
kb_rxcuis = {d["rxcui"] for d in kb["drugs"] if d.get("rxcui")}
xw = json.load(open("out/ciel_rxnorm_crosswalk.json"))["crosswalk"]
ciel_rxcuis = {rx for c in xw for rx in c["rxcuis"]}

union = sorted(kb_rxcuis | ciel_rxcuis)

cache = {}
if os.path.exists(CACHE):
    for line in open(CACHE):
        try:
            r = json.loads(line); cache[r["rxcui"]] = r["ingredients"]
        except Exception:
            pass

def ingredients(rxcui):
    # Single-ingredient (IN) RxCUIs for a concept. tty=IN decomposes a combination
    # product into its component ingredients; it deliberately excludes MIN
    # (multiple-ingredient) tokens, which would falsely bridge two distinct
    # ingredients that co-occur in some combination product. If nothing relates,
    # the concept is treated as its own ingredient.
    url = f"{RXBASE}/rxcui/{rxcui}/related.json?tty=IN"
    out = subprocess.run(["curl", "-s", "--max-time", "30", url], capture_output=True, text=True).stdout
    ings = set()
    try:
        groups = (json.loads(out).get("relatedGroup") or {}).get("conceptGroup") or []
        for g in groups:
            for p in (g.get("conceptProperties") or []):
                ings.add(p["rxcui"])
    except Exception:
        pass
    if not ings:
        ings = {rxcui}   # already an ingredient or no mapping; keep self
    return sorted(ings)

todo = [r for r in union if r not in cache]
print(f"RxCUIs to resolve: {len(todo)} ({len(cache)} cached) of {len(union)} total")
fh = open(CACHE, "a")
n = 0
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(ingredients, r): r for r in todo}
    for fut in as_completed(futs):
        r = futs[fut]
        try:
            ings = fut.result()
        except Exception:
            ings = [r]
        cache[r] = ings
        fh.write(json.dumps({"rxcui": r, "ingredients": ings}) + "\n"); n += 1
        if n % 500 == 0:
            fh.flush(); print(f"  {n}/{len(todo)}")
fh.flush(); fh.close()

# KB ingredient set
kb_ings = set()
for r in kb_rxcuis:
    kb_ings.update(cache.get(r, [r]))

covered = gaps = 0
covered_list, gap_list = [], []
for c in xw:
    c_ings = set()
    for rx in c["rxcuis"]:
        c_ings.update(cache.get(rx, [rx]))
    hit = c_ings & kb_ings
    if hit:
        covered += 1
        covered_list.append({"ciel_code": c["ciel_code"], "ciel_uuid": c.get("ciel_uuid"), "name": c["name"]})
    else:
        gaps += 1
        gap_list.append({"ciel_code": c["ciel_code"], "ciel_uuid": c.get("ciel_uuid"), "name": c["name"]})

total = len(xw)
summary = {
    "generated_on": "2026-07-21",
    "method": "Ingredient-level reconciliation: both CIEL RxCUIs and KB RxCUIs mapped to their RxNorm single-ingredient (tty=IN) RxCUIs before matching. Combination products decompose to component ingredients; multiple-ingredient (MIN) tokens are excluded so unrelated ingredients that co-occur in a combination are not falsely bridged.",
    "ciel_source": "CIEL v2026-07-20 (OCL export)",
    "ddinter_source": "DDInter 2.0",
    "ciel_drug_concepts_mapped_to_rxnorm": total,
    "ciel_drugs_with_ddinter_interactions": covered,
    "ciel_drugs_without_ddinter_data": gaps,
    "coverage_pct": round(100 * covered / max(1, total), 1),
    "kb_ingredient_rxcuis": len(kb_ings),
}
# committable aggregate-only summary (no bulk CIEL rows)
json.dump(summary, open("out/ciel_ddinter_coverage_summary.json", "w"), ensure_ascii=False, indent=2)
# detailed (gitignored) for local review
json.dump({"summary": summary, "covered": covered_list, "gaps": gap_list},
          open("out/ciel_ddinter_coverage.json", "w"), ensure_ascii=False)

for k, v in summary.items():
    print(f"{k}: {v}")
