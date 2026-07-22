"""
build_kb.py — reproducible build of the canonical DDI knowledge base.

Deterministic, offline. Reads the committed source inputs in src/ (the frozen
facts fetched once from DDInter / RxNorm / RxClass / CIEL, plus the clinician
curation decisions) and assembles out/ddi_knowledge_base.json — the normalized
knowledge base. No network access; the one-time acquisition of src/ is separate.

Pipeline:
  1. DDInter facts        src/drugs.jsonl, src/interactions.jsonl, src/ddi_mechanisms.json
  2. RxNorm normalization src/rxnorm.jsonl (name -> base RxCUI)
  3. canonicalize to IN   src/ingredient_cache.jsonl, src/rxnorm_names.jsonl
  4. clinician curation   src/curation.json (separations, remaps, gaps)
  5. CIEL bridge          src/ciel_crosswalk.json (ingredient-level match)
  6. ATC                  src/atc_cache.jsonl (pre-derived from RxClass)

Usage: python3 build_kb.py [--check]   (--check verifies against the committed file)
"""
import json, os, re, sys

S = "src/"
def jsonl(p):
    return [json.loads(l) for l in open(p)]

rxn = {r["ddinter_id"]: r for r in jsonl(S + "rxnorm.jsonl")}
ing = {r["rxcui"]: r["ingredients"] for r in jsonl(S + "ingredient_cache.jsonl")}
rxnames = {r["rxcui"]: r["name"] for r in jsonl(S + "rxnorm_names.jsonl")}
atc = {r["rxcui"]: r["atc"] for r in jsonl(S + "atc_cache.jsonl")}
curation = {o["id"]: o for o in json.load(open(S + "curation.json"))["overrides"]}
drugs_raw = jsonl(S + "drugs.jsonl")
interactions = [json.loads(l) for l in open(S + "interactions.jsonl")]
mech_src = {g["group_id"]: g for g in json.load(open(S + "ddi_mechanisms.json"))["groups"]}

# --- 3. canonicalize base RxCUI to its RxNorm single-ingredient (IN) concept ---
def ings(rx):
    return ing.get(rx, [rx]) if rx else []
def norm(s):
    s = (s or "").lower(); s = re.sub(r"\([^)]*\)", "", s)
    s = re.sub(r"\b(sodium|hydrochloride|sulfate|calcium|potassium|acetate|citrate|salt)\b", "", s)
    return re.sub(r"\s+", " ", s).strip()
def canonicalize(did, name):
    base = rxn.get(did, {}).get("rxcui")
    if not base:
        return None, None
    ig = ings(base)
    if ig == [base]:
        return base, rxn[did].get("rxnorm_name")
    if len(ig) == 1:
        return ig[0], rxnames.get(ig[0]) or rxn[did].get("rxnorm_name")
    dn = norm(name); cand = [(i, rxnames.get(i)) for i in ig]
    ex = [i for i, nm in cand if nm and norm(nm) == dn]
    sub = [i for i, nm in cand if nm and norm(nm) and norm(nm) in dn]
    if len(ex) == 1:
        return ex[0], rxnames.get(ex[0])
    if len(sub) == 1:
        return sub[0], rxnames.get(sub[0])
    return base, rxn[did].get("rxnorm_name")

# --- 5. CIEL ingredient-level index (concept ingredient set -> concept) ---
xw = json.load(open(S + "ciel_crosswalk.json"))["crosswalk"]
ing_to_ciel = {}
for c in xw:
    cset = set()
    for rx in c["rxcuis"]:
        cset |= set(ings(rx))
    entry = {"code": c["ciel_code"], "uuid": c.get("ciel_uuid"), "name": c["name"]}
    for i in cset:
        ing_to_ciel.setdefault(i, []).append(entry)
def ciel_for(rx):
    seen, out = set(), []
    for i in ings(rx):
        for e in ing_to_ciel.get(i, []):
            if e["code"] not in seen:
                seen.add(e["code"]); out.append(e)
    return sorted(out, key=lambda e: e["code"])

# --- assemble drugs ---
drugs = []
for d in drugs_raw:
    did, name = d["id"], d["name"]
    rx, rxname = canonicalize(did, name)
    if did in curation:
        rx, rxname = curation[did]["rxcui"], curation[did]["rxnorm_name"]
    drugs.append({
        "id": did, "name": name, "rxcui": rx, "rxnorm_name": rxname,
        "drugbank_id": d.get("drugbank_id"),
        "atc": atc.get(rx, []) if rx else [],
        "ciel": ciel_for(rx),
    })

# --- mechanisms: used groups only, stored once ---
used = {row[3] for row in interactions}
mechanisms = {gid: {"text": mech_src[gid]["mechanism"], "categories": mech_src[gid]["mechanism_categories"]}
              for gid in sorted(used, key=lambda x: int(x)) if gid in mech_src}

kb = {
    "metadata": {
        "schema_version": "1.0",
        "title": "OpenMRS DDI knowledge base (normalized)",
        "source": {"name": "DDInter 2.0", "url": "https://ddinter2.scbdd.com/",
                   "normalization": "RxNorm (NLM)", "bridge": "CIEL v2026-07-20"},
        "shape": {"drugs": len(drugs), "mechanisms": len(mechanisms), "interactions": len(interactions)},
        "format": {"interactions": "[drug_a_id, drug_b_id, severity, group_id]",
                   "note": "Reproducible build from src/ via build_kb.py; clinician decisions in src/curation.json."},
    },
    "mechanisms": mechanisms,
    "drugs": drugs,
    "interactions": interactions,
}

if "--check" in sys.argv:
    cur = json.load(open("out/ddi_knowledge_base.json"))
    ok = True
    for key in ("drugs", "mechanisms", "interactions"):
        if kb[key] != cur[key]:
            ok = False
            if key == "drugs":
                diff = [d["id"] for d, c in zip(kb["drugs"], cur["drugs"]) if d != c]
                print(f"MISMATCH in drugs: {len(diff)} differ, e.g. {diff[:10]}")
            else:
                print(f"MISMATCH in {key}")
    print("VERIFY:", "reproduces the committed KB exactly" if ok else "DIFFERENCES FOUND")
    sys.exit(0 if ok else 1)

json.dump(kb, open("out/ddi_knowledge_base.json", "w"), ensure_ascii=False)

# CIEL reverse index: patient CIEL concept UUID -> KB drug(s)
ciel_index = {}
for d in drugs:
    for e in d["ciel"]:
        idx = ciel_index.setdefault(e["uuid"], {"ciel_code": e["code"], "ciel_name": e["name"], "drugs": []})
        idx["drugs"].append({"ddinter_id": d["id"], "rxcui": d["rxcui"], "name": d["name"]})
json.dump({"metadata": {"description": "Reverse lookup for module use: CIEL concept UUID -> DDInter KB drug(s).",
                        "source": "CIEL v2026-07-20 + DDInter 2.0", "count": len(ciel_index)},
           "index": ciel_index}, open("out/ciel_index.json", "w"), ensure_ascii=False)

by_id = {d["id"]: d for d in drugs}
sample = [{"drug_a": {"id": a, "name": by_id[a]["name"], "rxcui": by_id[a]["rxcui"]},
           "drug_b": {"id": b, "name": by_id[b]["name"], "rxcui": by_id[b]["rxcui"]},
           "severity": s, "mechanism": mechanisms.get(g, {}).get("text"), "group_id": g}
          for a, b, s, g in interactions[:8]]
json.dump({"note": "Illustrative reconstructed rows from ddi_knowledge_base.json.", "interactions": sample},
          open("out/sample.json", "w"), ensure_ascii=False, indent=2)
print(f"built out/ddi_knowledge_base.json  drugs {len(drugs)} | mechanisms {len(mechanisms)} | interactions {len(interactions)}")
