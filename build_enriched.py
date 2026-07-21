import json, os

SEVMAP = {3: "Major", 2: "Moderate", 1: "Minor", 0: "Unknown"}

mech = json.load(open("out/ddi_mechanisms.json"))
groups = {g["group_id"]: g for g in mech["groups"]}

# backbone: authoritative per-pair severity + drug names, keyed by sorted pair
backbone = json.load(open("out/ddi_knowledge_base.json"))
bb_sev = {}
drug_name = {}
for r in backbone["interactions"]:
    a, b = r["drug_a"]["ddinter_id"], r["drug_b"]["ddinter_id"]
    bb_sev[tuple(sorted((a, b)))] = r["severity"]
    drug_name[a] = r["drug_a"]["name"]
    drug_name[b] = r["drug_b"]["name"]

# API pairs from the group walk
enriched = {}          # key -> record
drugbank = {}          # ddinter_id -> drugbank_id
sev_mismatch = 0
api_only = 0
groups_seen = set()
pair_rows = 0

for line in open("out/pairs.jsonl"):
    rec = json.loads(line)
    gid = rec["gid"]
    groups_seen.add(gid)
    g = groups.get(gid, {})
    for p in rec["pairs"]:
        pair_rows += 1
        a, b = p["a"], p["b"]
        key = tuple(sorted((a, b)))
        if p.get("adb"): drugbank[a] = p["adb"]
        if p.get("bdb"): drugbank[b] = p["bdb"]
        drug_name.setdefault(a, p["an"]); drug_name.setdefault(b, p["bn"])
        sev = bb_sev.get(key)
        if sev is None:
            api_only += 1
            sev = g.get("severity", "Unknown")
        elif sev != g.get("severity"):
            sev_mismatch += 1
        # first group wins; keep smallest gid deterministically
        if key not in enriched or int(gid) < int(enriched[key]["source_group_id"]):
            enriched[key] = {
                "id": f"{key[0]}__{key[1]}",
                "drug_a": {"ddinter_id": key[0], "name": drug_name[key[0]], "drugbank_id": drugbank.get(key[0]), "rxcui": None},
                "drug_b": {"ddinter_id": key[1], "name": drug_name[key[1]], "drugbank_id": drugbank.get(key[1]), "rxcui": None},
                "severity": sev,
                "mechanism": g.get("mechanism"),
                "management": None,
                "mechanism_categories": g.get("mechanism_categories", []),
                "source": "DDInter 2.0",
                "source_group_id": gid,
                "source_url": f"https://ddinter2.scbdd.com/server/inter-detail/{gid}/",
                "citation": "Xiong G, et al. DDInter 2.0. Nucleic Acids Research. 2025;53(D1):D1356-D1364.",
            }

# reconciliation vs backbone
bb_keys = set(bb_sev)
en_keys = set(enriched)
records = sorted(enriched.values(), key=lambda r: r["id"])
sev_dist = {}
mech_cov = 0
for r in records:
    sev_dist[r["severity"]] = sev_dist.get(r["severity"], 0) + 1
    if r["mechanism"]:
        mech_cov += 1

all_drugs = sorted({d for k in en_keys for d in k} | {d for k in bb_keys for d in k})
out = {
    "metadata": {
        "schema_version": "1.0",
        "title": "OpenMRS Chart Search AI - DDI Knowledge Base (fully enriched)",
        "generated_by": "DDInter 2.0 group walk (inter-list) joined to mechanism layer",
        "generated_on": "2026-07-21",
        "source": backbone["metadata"]["source"],
        "coverage": {
            "unique_drugs": len(all_drugs),
            "unique_interactions": len(records),
            "interactions_with_mechanism_text": mech_cov,
            "severity_distribution": sev_dist,
        },
        "severity_scale": backbone["metadata"]["severity_scale"],
        "notes": [
            "Every interaction carries its DDInter 2.0 mechanism description and mechanism-category flags via source_group_id.",
            "severity is the authoritative per-pair level from the bulk CSV where present, else the group level.",
            "management is null: DDInter's text is a mechanism/effect description and does not expose a discrete management field.",
            "rxcui is null pending RxNorm normalization (spec 4.2).",
            "Absence of a pair means DDInter has no record; report a knowledge gap, never a false 'no interaction'.",
        ],
    },
    "drugs": [{"ddinter_id": d, "name": drug_name.get(d), "drugbank_id": drugbank.get(d), "rxcui": None} for d in all_drugs],
    "interactions": records,
}
json.dump(out, open("out/ddi_knowledge_base_enriched.json", "w"), ensure_ascii=False)

print("groups walked          :", len(groups_seen), "/", len(groups))
print("pair rows returned     :", pair_rows)
print("unique enriched pairs  :", len(en_keys))
print("backbone (CSV) pairs   :", len(bb_keys))
print("  in both              :", len(en_keys & bb_keys))
print("  API-only (new)       :", len(en_keys - bb_keys))
print("  CSV-only (unenriched):", len(bb_keys - en_keys))
print("severity mismatches    :", sev_mismatch)
print("with mechanism text    :", mech_cov, f"({100*mech_cov//max(1,len(records))}%)")
print("severity distribution  :", sev_dist)
print("file size MB           : %.1f" % (os.path.getsize("out/ddi_knowledge_base_enriched.json") / 1e6))
