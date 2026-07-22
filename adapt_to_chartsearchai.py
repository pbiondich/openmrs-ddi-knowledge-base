"""
Adapter: ddi_kb_compact.json -> openmrs-module-chartsearchai drug-reference.json

Reads the canonical compact knowledge base (mechanisms table + drugs table +
interaction rows) and emits the module's drug-centric DrugReference format
(ADR Decision 24; consumed by JsonDrugReferenceSource with sourceFormat=json).
See docs/INTEGRATION.md and docs/PHASE2-PR-PROPOSAL.md.

Scope is parameterized. Default: CIEL-linked drugs (the OpenMRS formulary),
Major + Moderate severity. MODE=demo emits a small, self-contained test file.
"""
import json, sys, os

MODE = sys.argv[1] if len(sys.argv) > 1 else "full"
SEVERITIES = {"Major", "Moderate"}
DEMO_DRUGS = {"warfarin","acetylsalicylic acid","ibuprofen","simvastatin","clarithromycin",
              "methotrexate","digoxin","amiodarone","fluconazole","metformin","lisinopril",
              "spironolactone","tramadol","sertraline","omeprazole","ciprofloxacin"}

kb = json.load(open("out/ddi_kb_compact.json"))
mech = kb["mechanisms"]
drugs = {d["id"]: d for d in kb["drugs"]}

def first_atc(d):
    return d["atc"][0] if d.get("atc") else None

def aliases(d):
    al = [d["name"]]
    if d.get("rxnorm_name"):
        al.append(d["rxnorm_name"])
    for c in d.get("ciel", []):
        if c.get("name"):
            al.append(c["name"])
    seen, out = set(), []
    for a in al:
        a = a.strip().lower()
        if a and a not in seen:
            seen.add(a); out.append(a)
    return out

in_formulary = {did for did, d in drugs.items() if d.get("ciel")}
included = set(DEMO_DRUGS) if MODE == "demo" else None

# collect partners per drug within scope
partners = {}   # did -> list of (partner_did, severity, group_id)
for a, b, sev, gid in kb["interactions"]:
    if sev not in SEVERITIES:
        continue
    if a not in in_formulary or b not in in_formulary:
        continue
    partners.setdefault(a, []).append((b, sev, gid))
    partners.setdefault(b, []).append((a, sev, gid))

def note_for(sev, gid):
    text = mech.get(gid, {}).get("text")
    return f"{sev}. {text}" if text else f"{sev} severity interaction (DDInter 2.0; no mechanism description on file)."

entries = []
for did, plist in partners.items():
    d = drugs[did]
    if included is not None and d["name"].lower() not in included:
        continue
    inter, seen = [], set()
    for pdid, sev, gid in plist:
        if pdid in seen:
            continue
        p = drugs[pdid]
        if included is not None and p["name"].lower() not in included:
            continue   # demo is self-contained
        seen.add(pdid)
        obj = {"token": p["name"].lower(), "note": note_for(sev, gid)}
        pa = first_atc(p)
        if pa:
            obj["atc"] = pa
        inter.append(obj)
    inter.sort(key=lambda x: x["token"])
    entries.append({
        "id": d.get("rxcui") or d["id"],
        "name": d["name"],
        "aliases": aliases(d),
        "atcCodes": d.get("atc", []),
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
                    "DDI knowledge base (ddi_kb_compact.json). Each entry lists a drug's interacting "
                    "partners (Major/Moderate severity) with mechanism notes. Aliases include RxNorm "
                    "and CIEL concept names; atcCodes derived via RxNorm RxClass. Dosing and "
                    "contraindications are out of V1 scope."),
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
