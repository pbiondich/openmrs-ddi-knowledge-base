import subprocess, json, os, re
from concurrent.futures import ThreadPoolExecutor, as_completed

RXBASE = "https://rxnav.nlm.nih.gov/REST"
NAMES = "out/rxnorm_names.jsonl"

cache = {}
for line in open("out/ingredient_cache.jsonl"):
    r = json.loads(line); cache[r["rxcui"]] = r["ingredients"]

def ings(rx):
    return cache.get(rx, [rx])

enr = json.load(open("out/ddi_knowledge_base_enriched.json"))
drugs = enr["drugs"]

# candidate ingredient rxcuis needing names
need = set()
for d in drugs:
    ing = ings(d["rxcui"])
    if ing != [d["rxcui"]]:
        need.update(ing)

# fetch RxNorm names (resumable)
names = {}
if os.path.exists(NAMES):
    for line in open(NAMES):
        try:
            r = json.loads(line); names[r["rxcui"]] = r["name"]
        except Exception:
            pass

def rxname(rx):
    out = subprocess.run(["curl", "-s", "--max-time", "30",
        f"{RXBASE}/rxcui/{rx}/property.json?propName=RxNorm%20Name"], capture_output=True, text=True).stdout
    try:
        props = (json.loads(out).get("propConceptGroup") or {}).get("propConcept") or []
        return props[0]["propValue"] if props else None
    except Exception:
        return None

todo = [r for r in need if r not in names]
if todo:
    fh = open(NAMES, "a")
    with ThreadPoolExecutor(max_workers=8) as ex:
        futs = {ex.submit(rxname, r): r for r in todo}
        for fut in as_completed(futs):
            r = futs[fut]; nm = fut.result(); names[r] = nm
            fh.write(json.dumps({"rxcui": r, "name": nm}) + "\n")
    fh.close()
print("ingredient names known:", sum(1 for r in need if names.get(r)), "/", len(need))

def norm(s):
    s = (s or "").lower()
    s = re.sub(r"\([^)]*\)", "", s)              # drop qualifiers
    s = re.sub(r"\b(sodium|hydrochloride|sulfate|calcium|potassium|acetate|citrate|salt)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()

review = []   # residual cases for manual review
changed = 0

def canonical_for(d):
    global changed
    rx = d["rxcui"]; ing = ings(rx)
    if ing == [rx]:
        return None                               # already IN / unmapped
    if len(ing) == 1:
        return ing[0]                             # unambiguous
    # multiple ingredients: pick by name match against the drug name
    dn = norm(d["name"])
    cand = [(i, names.get(i)) for i in ing]
    exact = [i for i, nm in cand if nm and norm(nm) == dn]
    sub = [i for i, nm in cand if nm and norm(nm) and norm(nm) in dn]
    if len(exact) == 1:
        return exact[0]
    if len(sub) == 1:
        return sub[0]
    review.append({"name": d["name"], "rxcui": rx, "candidates": [{"rxcui": i, "name": names.get(i)} for i in ing],
                   "reason": "multi-ingredient, no single name match"})
    return None

def apply(path):
    global changed
    d = json.load(open(path))
    remap = {}
    for drug in d["drugs"]:
        can = canonical_for(drug)
        if can and can != drug["rxcui"]:
            remap[drug["rxcui"]] = can
            drug["rxcui_original"] = drug["rxcui"]
            drug["rxcui"] = can
            drug["rxnorm_name"] = names.get(can) or drug.get("rxnorm_name")
            drug["rxcui_canonicalized"] = True
            changed += 1
        if drug.get("rxcui_match") == "approximate":
            review.append({"name": drug["name"], "rxcui": drug["rxcui"], "reason": "approximate RxNorm match"})
    for it in d["interactions"]:
        for side in ("drug_a", "drug_b"):
            rx = it[side]["rxcui"]
            if rx in remap:
                it[side]["rxcui"] = remap[rx]
    json.dump(d, open(path, "w"), ensure_ascii=False)
    return d

apply("out/ddi_knowledge_base.json")
enr2 = apply("out/ddi_knowledge_base_enriched.json")

# residual distinct-drug collisions after canonicalization
import collections
by = collections.defaultdict(set)
for x in enr2["drugs"]:
    by[x["rxcui"]].add(x["name"])
collisions = {k: sorted(v) for k, v in by.items() if len(v) > 1}
# keep only likely-wrong collisions (names that are not formulation variants of each other)
def base(n): return norm(n)
wrong = {k: v for k, v in collisions.items() if len({base(n) for n in v}) > 1}

# dedupe review
seen = set(); review_u = []
for r in review:
    key = (r["name"], r["rxcui"], r["reason"])
    if key not in seen:
        seen.add(key); review_u.append(r)

json.dump({"generated_on": "2026-07-21",
           "canonicalized_to_ingredient": changed // 2,   # applied to two files
           "residual_review": review_u,
           "residual_shared_rxcui_distinct_drugs": wrong},
          open("out/rxcui_review.json", "w"), ensure_ascii=False, indent=2)

print("drugs canonicalized to ingredient (per file):", changed // 2)
print("residual review items (multi-ingredient + approximate):", len(review_u))
print("residual likely-wrong shared rxcuis:", len(wrong))
for k, v in list(wrong.items())[:10]:
    print("   ", k, "->", v)
