import json

kb = json.load(open("out/ddi_knowledge_base_enriched.json"))
kb_rxcuis = {d["rxcui"] for d in kb["drugs"] if d.get("rxcui")}
kb_by_rxcui = {}
for d in kb["drugs"]:
    if d.get("rxcui"):
        kb_by_rxcui.setdefault(d["rxcui"], d["name"])

xw = json.load(open("out/ciel_rxnorm_crosswalk.json"))["crosswalk"]

covered, gaps = [], []
for c in xw:
    hit = [rx for rx in c["rxcuis"] if rx in kb_rxcuis]
    rec = {"ciel_code": c["ciel_code"], "name": c["name"], "rxcuis": c["rxcuis"]}
    if hit:
        rec["ddinter_rxcuis"] = hit
        covered.append(rec)
    else:
        gaps.append(rec)

ciel_rx = {rx for c in xw for rx in c["rxcuis"]}
overlap_rx = ciel_rx & kb_rxcuis

summary = {
    "generated_on": "2026-07-21",
    "ciel_concepts_mapped_to_rxnorm": len(xw),
    "ciel_concepts_with_ddinter_interactions": len(covered),
    "ciel_concepts_without_ddinter_data": len(gaps),
    "coverage_pct": round(100 * len(covered) / max(1, len(xw)), 1),
    "distinct_rxcuis_ciel": len(ciel_rx),
    "distinct_rxcuis_kb": len(kb_rxcuis),
    "rxcui_overlap": len(overlap_rx),
    "note": "Join is on exact RxCUI. CIEL maps concepts to RxNorm at mixed term-type levels (ingredient, clinical drug, etc.), while this KB stores the ingredient-level RxCUI, so exact-match coverage is a lower bound; ingredient reconciliation (issue #4) would raise it.",
}
json.dump({"summary": summary, "covered": covered, "gaps": gaps},
          open("out/ciel_ddinter_coverage.json", "w"), ensure_ascii=False)

for k, v in summary.items():
    print(f"{k}: {v}")
print("\nsample covered CIEL drugs:")
for c in covered[:8]:
    print(f"  {c['name']}  (CIEL {c['ciel_code']}) -> DDInter rxcui {c['ddinter_rxcuis']}")
