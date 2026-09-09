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

Exclusions. A brand name becomes an alias downstream, and Chart Search AI matches aliases in
question prose with no length floor, so an alias that is also an ordinary word makes the word
resolve a drug ("does this align with...", "Sleep Aid", "Today"). Three rules drop those,
and the dropped list is committed beside the kept one (src/brand_names_excluded.json) so the
decision is inspectable and the build stays offline:
  1. three characters or fewer (Alo, DOK, Ery: acronyms, not names anyone asks by);
  2. every word is an ordinary (lower-case) dictionary word: Align, Today, Sleep Aid, Correct
     (New Formula). Capitalised dictionary entries are kept, because famous trademarks are in
     the dictionary too (Demerol, Dilantin, Dramamine);
  3. a first name (the system proper-names list, plus src/curation.json "brand_exclusions" for
     the ones it misses).
Dictionary: macOS /usr/share/dict/words (web2) and /usr/share/dict/propernames.

Usage: python3 fetch_brand_names.py             fetch from RxNav, then filter
       python3 fetch_brand_names.py --refilter  re-apply the rules to the fetched file, no network
"""
import subprocess, json, os, re, sys
from concurrent.futures import ThreadPoolExecutor, as_completed

RX = "https://rxnav.nlm.nih.gov/REST"
OUT = "src/brand_names.jsonl"
EXCLUDED = "src/brand_names_excluded.json"
WORDS, NAMES = "/usr/share/dict/words", "/usr/share/dict/propernames"

def load_words(path, keep):
    return {w.strip() for w in open(path, encoding="utf-8", errors="ignore") if w.strip() and keep(w.strip())}
common = {w.lower() for w in load_words(WORDS, lambda w: w[0].islower())}      # ordinary words only
first_names = {w.lower() for w in load_words(NAMES, lambda w: True)}
curated = {b.lower() for b in json.load(open("src/curation.json")).get("brand_exclusions", {}).get("brands", [])}

def exclusion_reason(brand):
    words = re.findall(r"[A-Za-z]+", brand)
    if brand.lower() in curated:
        return "listed in src/curation.json brand_exclusions"
    if len(brand) <= 3:
        return "three characters or fewer"
    if words and all(w.lower() in common for w in words):
        return "every word is an ordinary dictionary word"
    if len(words) == 1 and words[0].lower() in first_names and re.sub(r"[A-Za-z]", "", brand) == "":
        return "a first name"
    return None

def write_filtered(result, rxcuis):
    """result: rxcui -> unfiltered brand list. Writes the kept lists (stable order) to OUT and the
    dropped ones, with reason and the rxcuis they were fetched under, to EXCLUDED, so --refilter can
    put everything fetched back through the rules without touching the network."""
    excluded = {}
    with open(OUT, "w") as f:
        for rx in rxcuis:
            if rx not in result:
                continue
            kept = []
            for b in result[rx]:
                why = exclusion_reason(b)
                if why:
                    excluded.setdefault(b, {"reason": why, "rxcuis": []})["rxcuis"].append(rx)
                else:
                    kept.append(b)
            f.write(json.dumps({"rxcui": rx, "brand_names": kept}, ensure_ascii=False) + "\n")
    json.dump({"description": "Brand names fetch_brand_names.py fetched from RxNorm and dropped, with the rule each "
                              "fell to and the ingredient rxcuis it was fetched under. Kept beside "
                              "src/brand_names.jsonl so the exclusion is inspectable and reversible (--refilter).",
               "dictionary": "macOS /usr/share/dict/words (web2, lower-case entries) and /usr/share/dict/propernames, "
                             "plus src/curation.json brand_exclusions",
               "count": len(excluded), "excluded": dict(sorted(excluded.items()))},
              open(EXCLUDED, "w"), ensure_ascii=False, indent=1)
    return excluded

if "--refilter" in sys.argv:
    rows = [json.loads(l) for l in open(OUT)]
    prior = json.load(open(EXCLUDED))["excluded"] if os.path.exists(EXCLUDED) else {}
    result = {r["rxcui"]: set(r["brand_names"]) for r in rows}
    for b, e in prior.items():                          # everything fetched = kept + previously dropped
        for rx in e["rxcuis"]:
            result.setdefault(rx, set()).add(b)
    excluded = write_filtered({rx: sorted(v) for rx, v in result.items()}, [r["rxcui"] for r in rows])
    print(f"refiltered {OUT}: {len(excluded)} brand names excluded -> {EXCLUDED}")
    sys.exit(0)

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

excluded = write_filtered(result, rxcuis)

kept = [json.loads(l)["brand_names"] for l in open(OUT)]
print(f"wrote {OUT}: {len(result)}/{len(rxcuis)} rxcuis fetched | {sum(1 for k in kept if k)} with >=1 brand "
      f"| {sum(len(k) for k in kept)} brand-name links | {len(excluded)} brand names excluded -> {EXCLUDED}")
failed = [r for r in rxcuis if r not in result]
if failed:
    print(f"FAILED {len(failed)} (rerun to retry): {failed[:10]}")
    raise SystemExit(1)
