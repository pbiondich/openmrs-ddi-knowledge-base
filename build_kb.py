"""
build_kb.py — validate the knowledge base and refresh the sample.

The canonical source of truth is ddi_kb_compact.json (normalized: a mechanisms
table stored once, a drugs table with RxCUI/ATC/CIEL, and interaction rows that
reference both). This validates that file (referential integrity + shape) and
regenerates a small readable sample. The hand-curated clinical decisions live in
the source data, not in code, so the compact file is the curated source of
record rather than a rebuild output.

Usage: python3 build_kb.py
"""
import json, os, sys

SRC = "out/ddi_kb_compact.json"
VALID_SEVERITY = {"Major", "Moderate", "Minor", "Unknown"}

def fail(msg):
    print("BUILD FAILED:", msg); sys.exit(1)

kb = json.load(open(SRC))
mech = kb.get("mechanisms", {})
drugs = kb.get("drugs", [])
inter = kb.get("interactions", [])
drug_ids = {d["id"] for d in drugs}

# --- validate referential integrity ---
errors = 0
for d in drugs:
    if not d.get("id") or not d.get("name"):
        errors += 1
badref = badgid = badsev = 0
for row in inter:
    if len(row) != 4:
        errors += 1; continue
    a, b, sev, gid = row
    if a not in drug_ids or b not in drug_ids:
        badref += 1
    if gid not in mech:
        badgid += 1
    if sev not in VALID_SEVERITY:
        badsev += 1
if errors or badref or badgid or badsev:
    fail(f"integrity: {errors} bad drugs, {badref} dangling drug refs, "
         f"{badgid} dangling group ids, {badsev} bad severities")

# metadata shape sanity
shape = kb.get("metadata", {}).get("shape", {})
if shape.get("drugs") != len(drugs) or shape.get("mechanisms") != len(mech) or shape.get("interactions") != len(inter):
    fail(f"metadata.shape {shape} != actual (drugs {len(drugs)}, mechanisms {len(mech)}, interactions {len(inter)})")

# --- emit a small readable sample (reconstructed rows) ---
by_id = {d["id"]: d for d in drugs}
sample = []
for a, b, sev, gid in inter[:8]:
    m = mech.get(gid, {})
    sample.append({
        "drug_a": {"id": a, "name": by_id[a]["name"], "rxcui": by_id[a].get("rxcui")},
        "drug_b": {"id": b, "name": by_id[b]["name"], "rxcui": by_id[b].get("rxcui")},
        "severity": sev,
        "mechanism": m.get("text"),
        "mechanism_categories": m.get("categories", []),
        "group_id": gid,
    })
json.dump({"note": "Reconstructed interaction rows (join interactions -> drugs and mechanisms). Illustrative sample of the canonical ddi_kb_compact.json.", "interactions": sample},
          open("out/sample.json", "w"), ensure_ascii=False, indent=2)

sev = {}
for _, _, s, _ in inter:
    sev[s] = sev.get(s, 0) + 1
with_mech = sum(1 for _, _, _, g in inter if mech.get(g, {}).get("text"))
raw = os.path.getsize(SRC) / 1e6
print("validation: OK (referential integrity + shape)")
print(f"drugs {len(drugs)} | mechanisms {len(mech)} | interactions {len(inter)}")
print(f"severity {sev}")
print(f"interactions with mechanism text: {with_mech} ({100*with_mech//len(inter)}%)")
print(f"knowledge base: {SRC} ({raw:.1f} MB)")
print("wrote out/sample.json")
