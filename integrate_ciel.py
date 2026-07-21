import json, os

# ingredient cache: rxcui -> [ingredient rxcuis]
cache = {}
for line in open("out/ingredient_cache.jsonl"):
    r = json.loads(line); cache[r["rxcui"]] = r["ingredients"]

def ings(rxcui):
    return set(cache.get(rxcui, [rxcui])) if rxcui else set()

# crosswalk: CIEL concept -> rxcuis; index each CIEL concept by its ingredient set
xw = json.load(open("out/ciel_rxnorm_crosswalk.json"))["crosswalk"]
ing_to_ciel = {}   # ingredient rxcui -> list of CIEL concept dicts
for c in xw:
    c_ings = set()
    for rx in c["rxcuis"]:
        c_ings |= ings(rx)
    entry = {"ciel_code": c["ciel_code"], "ciel_uuid": c.get("ciel_uuid"), "name": c["name"]}
    for i in c_ings:
        ing_to_ciel.setdefault(i, []).append(entry)

def ciel_for_rxcui(rxcui):
    seen, out = set(), []
    for i in ings(rxcui):
        for e in ing_to_ciel.get(i, []):
            if e["ciel_code"] not in seen:
                seen.add(e["ciel_code"]); out.append(e)
    return sorted(out, key=lambda e: e["ciel_code"])

def integrate(path, gz=False):
    d = json.load(open(path))
    linked = 0
    ciel_index = {}   # ciel_uuid -> {ciel_code, name, drugs:[...]}
    for drug in d["drugs"]:
        cs = ciel_for_rxcui(drug.get("rxcui"))
        drug["ciel_concepts"] = cs
        if cs:
            linked += 1
        for e in cs:
            idx = ciel_index.setdefault(e["ciel_uuid"], {"ciel_code": e["ciel_code"], "ciel_name": e["name"], "drugs": []})
            idx["drugs"].append({"ddinter_id": drug["ddinter_id"], "rxcui": drug.get("rxcui"), "name": drug["name"]})
    d["metadata"].setdefault("coverage", {})["ciel"] = {
        "drugs_with_ciel_concepts": linked, "drugs_total": len(d["drugs"]),
        "ciel_concepts_linked": len(ciel_index),
        "source": "CIEL v2026-07-20 (OCL export)",
        "method": "Ingredient-level match: a CIEL concept is linked to a KB drug when their RxNorm ingredient sets intersect (includes brand/product and combination concepts via their ingredients)."
    }
    json.dump(d, open(path, "w"), ensure_ascii=False)
    print(f"{os.path.basename(path):38} drugs w/ CIEL concepts: {linked}/{len(d['drugs'])}  | CIEL concepts linked: {len(ciel_index)}")
    return ciel_index

integrate("out/ddi_knowledge_base.json")
idx = integrate("out/ddi_knowledge_base_enriched.json")

# module-facing reverse index: patient CIEL concept UUID -> KB drug(s)
json.dump({"metadata": {"description": "Reverse lookup for module use: CIEL concept UUID -> DDInter KB drug(s). Given a patient's charted CIEL medication concept, resolve to the drug(s) in ddi_knowledge_base_enriched.json to check interactions.",
                        "source": "CIEL v2026-07-20 + DDInter 2.0", "generated_on": "2026-07-21",
                        "count": len(idx)},
           "index": idx}, open("out/ciel_index.json", "w"), ensure_ascii=False)
print("ciel_index.json entries:", len(idx))
