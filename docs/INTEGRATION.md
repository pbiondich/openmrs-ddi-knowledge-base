# Integrating this knowledge base into Chart Search AI

## The fit

The Chart Search AI module (`openmrs-module-chartsearchai`) already has the seam we need. Its drug-reference feature reads its clinical knowledge from a swappable dataset, chosen at runtime by the `chartsearchai.drugReference.sourceFormat` global property, behind a `DrugReferenceSource` interface (ADR Decision 24). It ships today with a small curated `drug-reference.json` seeded from the WHO Model List of Essential Medicines for Children, and it was explicitly designed so an authoritative dataset could be pointed at it instead of hand-maintaining that file. That curated seed is the same "handful of drugs, returns nothing for the rest" prototype the original spec set out to replace.

So this is not a re-architecture. The work is an adapter from our knowledge base into the shape the module already consumes, plus a decision about how big a dataset to ship.

## The one structural difference

The module's model is drug-centric and ours is pair-centric. A module entry is one drug that lists its interacting partners:

```json
{ "id": "...", "name": "...", "aliases": [...], "atcCodes": [...],
  "interactions": [ { "token": "warfarin", "atc": "B01AA03", "note": "..." } ],
  "contraindications": [...], "ageBands": [...], "source": "..." }
```

Our record is one interacting pair (`drug_a`, `drug_b`, `severity`, `mechanism`). The transform is a group-by: for each drug, collect every pair it appears in and emit one entry whose `interactions[]` are the partners. Because our data is symmetric, each pair contributes to both drugs' entries, which is exactly what the module expects (it matches from either side).

## Field mapping

| Module field | From our KB | Notes |
|---|---|---|
| `id` | the drug's `rxcui` (fallback `ddinter_id`) | Must be stable and non-blank; the module uses it as the citation identifier. |
| `name` | `name` | |
| `aliases` | `name` + `rxnorm_name` + the names of its linked `ciel_concepts` | Lowercased, de-duplicated. The CIEL names are the real win: they give brand/generic synonyms drawn from the same dictionary the chart uses. |
| `atcCodes` | not in our KB yet | The gap. See below. |
| `interactions[].token` | partner drug `name` | The module matches this against the patient's active orders and each entry's aliases. |
| `interactions[].atc` | partner's ATC | Same gap as `atcCodes`. |
| `interactions[].note` | `severity` + `mechanism` | e.g. `"Major. <mechanism text>"`. Our mechanism prose is richer than the seed's notes. |
| `source` | `"DDInter 2.0 (via openmrs-ddi-knowledge-base)"` | |
| `contraindications` | left empty | Drug-allergy and drug-condition are V2 in the spec; the module tolerates empty. |
| `ageBands` | left empty | Dosing is out of our scope; the module age-gates gracefully when absent. |

## The ATC gap, and why it matters

Unlike the project chartsearchai adapted its schema from, this module makes ATC codes load-bearing: `DrugReference.atcSubgroups()` (the ATC level-4 prefix) drives the validator's cross-reactivity and duplicate-therapy checks, the order-driven matcher, and relevance-scoped injection. Our KB carries RxCUI, DrugBank, and CIEL identifiers but not ATC.

Two ways to close it, in order of preference:
1. Derive ATC from RxNorm. The NLM RxClass API returns ATC codes for an RxCUI (`/rxclass/class/byRxcui?rxcui=<id>&relaSource=ATC`). One pass over our 2,283 drugs produces an RxCUI-to-ATC map we bundle and join in. This is the same maintenance-free, public-source posture as the rest of the build.
2. Ship without ATC and rely on name-token matching only. The core "drug A interacts with drug B" check still works (it matches by `token`), but the class-based reasoning the module is proud of goes dark. Acceptable as a first cut, not as the destination.

Recommendation: derive ATC. It is one bounded RxClass pass and it lights up the module's best features.

## A value-add the current design doesn't have: CIEL-direct matching

The module matches a patient's active orders by ATC. In an OpenMRS chart, though, orders reference CIEL concepts directly, so our `ciel_index.json` (CIEL concept UUID to KB drug) is a more precise matcher than ATC for exactly this environment. Worth offering upstream as an optional order-matching path alongside ATC, since it removes a normalization hop.

## Scale, and the two-phase plan

The honest constraint: a full drug-centric file is large. 2,283 drugs, each listing its partners, is on the order of 590,000 interaction objects once both sides of every pair are written out, which is a sizable JSON to bundle and to load fully into memory. That shapes a phased approach.

### Phase 1 — data-only drop-in (no module code)

Generate a module-format `drug-reference.json` from our KB, point `GP_DRUG_REFERENCE_DATA_FILE_PATH` at it, keep `sourceFormat=json`. This validates the entire pipeline end to end with zero changes to the module, which is the whole point of ADR-24.

To keep the file sane, scope it: the strongest first cut is the intersection with a real formulary (the CIEL-linked drugs, or an implementation's own list), optionally dropping `Minor`/`Unknown` severities. That turns "295K pairs" into a few thousand clinically actionable ones for a given deployment, with mechanism notes attached. The adapter takes the scope as a parameter so each implementation can widen or narrow it.

### Phase 2 — a pluggable source for the full dataset (module PR)

Contribute a `DdiDrugReferenceSource implements DrugReferenceSource` and a `sourceFormat=ddinter`, reading our KB (`ddi_knowledge_base.json`) and materializing `DrugReference` objects, indexed by RxCUI and name so the full set scales without a giant expanded file. This is the production path and a natural upstream contribution. Two small model additions are worth proposing alongside it:
- a `severity` field on `Interaction`, so safety chips can be ranked (Major vs Minor) rather than flattened into prose; and
- the optional CIEL-concept order matcher described above.

## What stays deferred

Consistent with the V1 spec: no dosing (`ageBands`), no drug-allergy or drug-condition contraindications. Those are real module capabilities, but they need data we deliberately did not build in V1. Leaving them empty is correct, not a shortfall, and the module already degrades cleanly on empty.

## How we would know it works

The module has the test surface to prove the integration: `DrugSafetyValidatorTest`, `JsonDrugReferenceSourceTest`, and a `drug-safety-eval.json` eval set. The Phase 1 check is to load our generated file through the existing JSON source and run those against a handful of known-dangerous pairs from our data (warfarin plus an NSAID, simvastatin plus a strong CYP3A4 inhibitor) to confirm the validator fires with our notes and citations.

## Phase 1 build (done)

The adapter is `adapt_to_chartsearchai.py`. It reads the canonical `ddi_knowledge_base.json` (whose drugs table already carries the ATC codes, pre-derived from RxNorm RxClass) and emits the module's `drug-reference.json` shape (`{entries: [...]}`, drug-centric, with `interactions[].{token, atc, note}`), parameterized by severity and formulary scope. Two artifacts are produced:

| File | Scope | Contents |
|---|---|---|
| `dist/chartsearchai-drug-reference-demo.json` (~0.1 MB) | 16 well-known drugs, self-contained (interactions among the set only) | A quick-to-load set for testing the module end to end. |
| `dist/chartsearchai-drug-reference.json` (~180 MB) | full formulary, Major+Moderate | 1,907 entries, 386,987 interaction objects. Not committed (regenerable); build with `python3 adapt_to_chartsearchai.py full`. |

ATC codes were derived for 1,712 of the 1,907 entries; the rest are biologics, vaccines, and contrast agents that RxNorm does not place in ATC. Aliases include RxNorm and CIEL concept names (so `simvastatin` also matches its CIEL combination-product names).

The ~180 MB raw full file is the concrete confirmation of the scale point above: a full drug-centric expansion is too large to bundle and load as a flat file, so an implementation should either scope the adapter to its own formulary or, better, adopt the Phase 2 pluggable source. The demo file is the artifact to actually load through the module's JSON source.

Validation against known-dangerous pairs (all fire, at `Major`, with real mechanism notes and partner ATC): warfarin × ibuprofen, warfarin × aspirin, simvastatin × clarithromycin, methotrexate × ibuprofen, digoxin × amiodarone, ciprofloxacin × warfarin. One refinement noted for Phase 2: RxClass returns every ATC membership including combination products, so a few entries carry extra `atcCodes` beyond the drug's own ingredient class; preferring the ingredient-level ATC would tighten the class-based matching.

## Open questions for the module maintainers

1. Is a bundled dataset of a few thousand scoped entries acceptable for Phase 1, or do they want the pluggable source (Phase 2) from the start?
2. Would they take a `severity` field on `Interaction` and an optional CIEL-concept matcher upstream?
3. What is their preferred formulary scoping for a shipped default: CIEL-linked drugs, WHO EML, or implementation-supplied?
