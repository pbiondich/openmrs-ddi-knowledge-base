import ijson, json

SC = "/private/tmp/claude-501/-Users-paul/8a25946f-06e2-43ac-b55d-a39dcec918cf/scratchpad"
EXPORT = f"{SC}/export.json"

# Pass 1: Drug-class concepts
drugs = {}   # ciel_code -> {uuid, name}
with open(EXPORT, "rb") as f:
    for c in ijson.items(f, "concepts.item"):
        if c.get("concept_class") == "Drug" and not c.get("retired"):
            drugs[str(c["id"])] = {"ciel_uuid": c.get("external_id"), "name": c.get("display_name")}
print("CIEL Drug concepts:", len(drugs))

# Pass 2: CIEL -> RxNORM mappings
xwalk = {}   # ciel_code -> {name, uuid, rxcuis:set, map_types:set}
n_map = 0
with open(EXPORT, "rb") as f:
    for m in ijson.items(f, "mappings.item"):
        if m.get("retired"):
            continue
        if m.get("to_source_name") != "RxNORM":
            continue
        n_map += 1
        code = str(m.get("from_concept_code"))
        if code not in drugs:
            continue  # keep to Drug-class concepts
        x = xwalk.setdefault(code, {"ciel_code": code, "ciel_uuid": drugs[code]["ciel_uuid"],
                                    "name": drugs[code]["name"], "rxcuis": set(), "map_types": set()})
        x["rxcuis"].add(str(m.get("to_concept_code")))
        x["map_types"].add(m.get("map_type"))

for x in xwalk.values():
    x["rxcuis"] = sorted(x["rxcuis"])
    x["map_types"] = sorted(x["map_types"])

json.dump({"source": "CIEL v2026-07-20 (OCL export)", "generated_on": "2026-07-21",
           "ciel_drug_concepts": len(drugs), "drug_concepts_mapped_to_rxnorm": len(xwalk),
           "crosswalk": list(xwalk.values())},
          open("out/ciel_rxnorm_crosswalk.json", "w"), ensure_ascii=False)

print("total CIEL->RxNORM mappings seen:", n_map)
print("Drug concepts with an RxNorm mapping:", len(xwalk))
print("Drug concepts WITHOUT any RxNorm mapping:", len(drugs) - len(xwalk))
