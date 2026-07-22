"""
Adapter: openmrs-ddi-knowledge-base -> openmrs-module-chartsearchai drug-reference.json

Transforms our pair-centric interaction knowledge base into the module's
drug-centric DrugReference format (ADR Decision 24; consumed by
JsonDrugReferenceSource with sourceFormat=json). See docs/INTEGRATION.md.

Scope is parameterized. The shipped default:
  - entries: CIEL-linked drugs (the OpenMRS formulary)
  - interactions: Major + Moderate severity, both ends CIEL-linked
Run with MODE=demo for a small, curated, quick-to-load test file.
"""
import json, sys, os, re

MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
SEVERITIES = {"Major", "Moderate"}          # default clinical scope
DEMO_DRUGS = {"warfarin","acetylsalicylic acid","ibuprofen","simvastatin","clarithromycin",
              "methotrexate","digoxin","amiodarone","fluconazole","metformin","lisinopril",
              "spironolactone","tramadol","sertraline","omeprazole","ciprofloxacin"}

kb = json.load(open("out/ddi_knowledge_base_enriched.json"))
drugs = {d["ddinter_id"]: d for d in kb["drugs"]}

atc = {}
if os.path.exists("out/atc_cache.jsonl"):
    for line in open("out/atc_cache.jsonl"):
        try:
            r = json.loads(line); atc[r["rxcui"]] = r["atc"]
        except Exception:
            pass

def atc_codes(d):
    return atc.get(d.get("rxcui"), []) if d.get("rxcui") else []

def first_atc(d):
    cs = atc_codes(d)
    return cs[0] if cs else None

def aliases(d):
    al = [d["name"]]
    if d.get("rxnorm_name"):
        al.append(d["rxnorm_name"])
    for c in d.get("ciel_concepts", []):
        if c.get("name"):
            al.append(c["name"])
    seen, out = set(), []
    for a in al:
        a = a.strip().lower()
        if a and a not in seen:
            seen.add(a); out.append(a)
    return out

in_formulary = {did for did, d in drugs.items() if d.get("ciel_concepts")}

# collect interactions per drug within scope
partners = {}   # did -> list of (partner_did, severity, mechanism)
for r in kb["interactions"]:
    if r["severity"] not in SEVERITIES:
        continue
    a, b = r["drug_a"]["ddinter_id"], r["drug_b"]["ddinter_id"]
    if a not in in_formulary or b not in in_formulary:
        continue
    partners.setdefault(a, []).append((b, r["severity"], r["mechanism"]))
    partners.setdefault(b, []).append((a, r["severity"], r["mechanism"]))

def note_for(sev, mech):
    if mech:
        return f"{sev}. {mech}"
    return f"{sev} severity interaction (DDInter 2.0; no mechanism description on file)."

entries = []
included = set(DEMO_DRUGS) if MODE == "demo" else None
for did, plist in partners.items():
    d = drugs[did]
    if included is not None and d["name"].lower() not in included:
        continue
    inter = []
    seen = set()
    for pdid, sev, mech in plist:
        if pdid in seen:
            continue
        p = drugs[pdid]
        # demo is self-contained: only interactions among the demo drugs
        if included is not None and p["name"].lower() not in included:
            continue
        seen.add(pdid)
        obj = {"token": p["name"].lower(), "note": note_for(sev, mech)}
        pa = first_atc(p)
        if pa:
            obj["atc"] = pa
        inter.append(obj)
    inter.sort(key=lambda x: x["token"])
    entries.append({
        "id": d.get("rxcui") or d["ddinter_id"],
        "name": d["name"],
        "aliases": aliases(d),
        "atcCodes": atc_codes(d),
        "ageBands": [],
        "interactions": inter,
        "contraindications": [],
        "source": "DDInter 2.0 (via openmrs-ddi-knowledge-base)",
    })

entries.sort(key=lambda e: e["name"].lower())
dataset = {
    "version": "1.0",
    "source": "DDInter 2.0, RxNorm, CIEL (openmrs-ddi-knowledge-base)",
    "description": ("Drug-drug interaction reference for chartsearchai, generated from the OpenMRS "
                    "DDI knowledge base. Each entry lists a drug's interacting partners (Major/Moderate "
                    "severity) with mechanism notes. Aliases include RxNorm and CIEL concept names; "
                    "atcCodes derived via RxNorm RxClass. Dosing and contraindications are out of V1 scope."),
    "entries": entries,
}
os.makedirs("dist", exist_ok=True)
out = f"dist/chartsearchai-drug-reference{'-demo' if MODE=='demo' else ''}.json"
json.dump(dataset, open(out, "w"), ensure_ascii=False, indent=1 if MODE == "demo" else None)

n_inter = sum(len(e["interactions"]) for e in entries)
n_atc = sum(1 for e in entries if e["atcCodes"])
print(f"MODE={MODE}")
print(f"entries: {len(entries)} | interaction objects: {n_inter} | entries with ATC: {n_atc}")
print(f"file: {out} ({os.path.getsize(out)/1e6:.1f} MB)")
