"""
fetch_brand_names.py — fetch each drug's brand names from RxNorm (RxNav), by ingredient RxCUI.

Produces src/brand_names.jsonl (rxcui -> [brand names]), a committed build input that
build_kb.py joins into the drugs table as brand_names. Needs network (RxNav).

Why: a clinician's question is where brand names live ("is it safe to give her
panadol?"), and until this the knowledge base named a drug only by its DDInter name,
its RxNorm generic name, and its CIEL concept names, so a brand-name question resolved
to nothing and the asked-about drug escaped checking (issue #5).

Source: RxNav `rxcui/{rxcui}/related.json?tty=BN`, the brand-name (BN) concepts related
to the ingredient. That includes brands of combination products (Vytorin lists under both
simvastatin and ezetimibe), which is the right behaviour: a question about the brand
should check every ingredient it contains, as CIEL combination names already do.
RxNorm is US-centric: Panadol is present, regional brands such as Calpol are not.
"""
import subprocess, json, os
from concurrent.futures import ThreadPoolExecutor, as_completed

RX = "https://rxnav.nlm.nih.gov/REST"
OUT = "src/brand_names.jsonl"

# The ingredient RxCUIs the built drugs table carries (as derive_atc.py does), so the brand list is
# keyed exactly as build_kb.py will join it.
rxcuis = sorted({d["rxcui"] for d in json.load(open("out/ddi_knowledge_base.json"))["drugs"] if d.get("rxcui")})

def brands(rx):
    out = subprocess.run(["curl", "-s", "--max-time", "30", f"{RX}/rxcui/{rx}/related.json?tty=BN"],
                         capture_output=True, text=True).stdout
    names = set()
    try:
        for g in (json.loads(out).get("relatedGroup") or {}).get("conceptGroup") or []:
            for c in g.get("conceptProperties") or []:
                if c.get("name"):
                    names.add(c["name"].strip())
    except Exception:
        return rx, None                       # not recorded, so a rerun retries it
    return rx, sorted(names)

result = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    futs = {ex.submit(brands, r): r for r in rxcuis}
    n = 0
    for fut in as_completed(futs):
        rx, names = fut.result()
        if names is not None:
            result[rx] = names
        n += 1
        if n % 400 == 0:
            print(f"  {n}/{len(rxcuis)}", flush=True)

with open(OUT, "w") as f:
    for rx in rxcuis:                        # stable rxcui order
        if rx in result:
            f.write(json.dumps({"rxcui": rx, "brand_names": result[rx]}, ensure_ascii=False) + "\n")

withb = sum(1 for v in result.values() if v)
total = sum(len(v) for v in result.values())
print(f"wrote {OUT}: {len(result)}/{len(rxcuis)} rxcuis fetched | {withb} with >=1 brand | {total} brand-name links")
failed = [r for r in rxcuis if r not in result]
if failed:
    print(f"FAILED {len(failed)} (rerun to retry): {failed[:10]}")
    raise SystemExit(1)
