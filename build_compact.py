"""
Build the compact, normalized DDI dataset: the scale fix.

The enriched KB inlines the full mechanism text on every one of ~295K
interactions, but there are only ~8,466 distinct mechanisms. This normalizes
that: mechanisms are stored once, and interactions reference them by group id.
This is the artifact the Phase 2 DdiDrugReferenceSource is meant to read; the
verbose enriched file is a denormalized convenience view generated from the
same facts.
"""
import json, os

kb = json.load(open("out/ddi_knowledge_base_enriched.json"))
mech_src = {g["group_id"]: g for g in json.load(open("out/ddi_mechanisms.json"))["groups"]}

atc = {}
for line in open("out/atc_cache.jsonl"):
    try:
        r = json.loads(line); atc[r["rxcui"]] = r["atc"]
    except Exception:
        pass

# mechanisms table: only the groups actually referenced, stored once
used_gids = {r["source_group_id"] for r in kb["interactions"] if r.get("source_group_id")}
mechanisms = {}
for gid in sorted(used_gids, key=lambda x: int(x)):
    g = mech_src.get(gid)
    if not g:
        continue
    mechanisms[gid] = {"text": g["mechanism"], "categories": g["mechanism_categories"]}

# drugs table
drugs = []
for d in kb["drugs"]:
    drugs.append({
        "id": d["ddinter_id"],
        "name": d["name"],
        "rxcui": d.get("rxcui"),
        "rxnorm_name": d.get("rxnorm_name"),
        "drugbank_id": d.get("drugbank_id"),
        "atc": atc.get(d.get("rxcui"), []) if d.get("rxcui") else [],
        "ciel": [{"code": c["ciel_code"], "uuid": c.get("ciel_uuid"), "name": c.get("name")}
                 for c in d.get("ciel_concepts", [])],
    })

# interactions: compact array form [drug_a_id, drug_b_id, severity, group_id]
interactions = [[r["drug_a"]["ddinter_id"], r["drug_b"]["ddinter_id"], r["severity"], r["source_group_id"]]
                for r in kb["interactions"]]

out = {
    "metadata": {
        "schema_version": "1.0-compact",
        "title": "OpenMRS DDI knowledge base (normalized/compact)",
        "generated_on": "2026-07-21",
        "source": kb["metadata"]["source"],
        "shape": {
            "drugs": len(drugs),
            "mechanisms": len(mechanisms),
            "interactions": len(interactions),
        },
        "format": {
            "interactions": "[drug_a_id, drug_b_id, severity, group_id]; join group_id -> mechanisms{} for text+categories; join *_id -> drugs[] by id",
            "note": "Normalized: each mechanism stored once (was inlined on every interaction in the enriched view). This is the read form for tooling and the Phase 2 module source.",
        },
    },
    "mechanisms": mechanisms,
    "drugs": drugs,
    "interactions": interactions,
}
os.makedirs("out", exist_ok=True)
json.dump(out, open("out/ddi_kb_compact.json", "w"), ensure_ascii=False)
import gzip
with gzip.open("out/ddi_kb_compact.json.gz", "wt", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False)

raw = os.path.getsize("out/ddi_kb_compact.json") / 1e6
gz = os.path.getsize("out/ddi_kb_compact.json.gz") / 1e6
enr_gz = os.path.getsize("out/ddi_knowledge_base_enriched.json.gz") / 1e6
print(f"drugs {len(drugs)} | mechanisms {len(mechanisms)} | interactions {len(interactions)}")
print(f"compact: {raw:.1f} MB raw, {gz:.1f} MB gz")
print(f"(enriched denormalized view: {os.path.getsize('out/ddi_knowledge_base_enriched.json')/1e6:.0f} MB raw, {enr_gz:.1f} MB gz)")
