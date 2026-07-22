# Proposal: a DDInter-backed pluggable drug-reference source

*Draft for the `openmrs-module-chartsearchai` maintainers. Companion to the data project at [openmrs-ddi-knowledge-base](https://github.com/pbiondich/openmrs-ddi-knowledge-base) and its [integration plan](./INTEGRATION.md).*

## What this proposes

A new `DrugReferenceSource` implementation, `DdiDrugReferenceSource`, selected by `chartsearchai.drugReference.sourceFormat=ddinter`, that backs the drug-reference feature with the full DDInter 2.0 interaction set (about 295,000 pairs across 2,283 drugs) instead of the hand-curated `drug-reference.json` seed. It changes no existing behavior: `json` stays the default, and this is one more opt-in adapter behind the same seam ADR Decision 24 already established.

The motivation is the one the original Chart Search AI spec set out to solve: the curated seed covers a handful of drugs and returns nothing for the rest, and it shifts curation onto implementers. A public-source dataset removes both problems. DDInter is open-access, offline-capable, and requires no implementer maintenance; RxNorm and CIEL supply the identifiers the module already reasons over.

## Why a new source rather than a bigger JSON

We built the data-only path first (Phase 1: generate a `drug-reference.json` in the existing format). It works, and it is the right way to validate the pipeline, but it does not scale: the full drug-centric expansion is about 180 MB as a flat file, because DDInter's per-group mechanism description is duplicated across every pair in the group. The size is note redundancy, not drug breadth, so scoping by formulary helps less than expected.

A dedicated source fixes this at the root, and the fix is in the data, not a runtime trick. There are only 8,234 distinct mechanism descriptions behind those 295,000 pairs, so we normalized the dataset: mechanisms are stored once and interactions reference them by group id. The measured result is `ddi_kb_compact.json` at **18.9 MB raw (2.0 MB gzipped)**, against the 270 MB denormalized view and the 180 MB flat module-format expansion. The source loads the mechanism table into a map and hands every interaction note the same shared `String` instance, so in-memory note cost is bounded by the ~8,200 unique strings, not the 295,000 pairs. No 180 MB artifact, and the `List<DrugReference>` stays reasonable.

## Design

### The source

```java
package org.openmrs.module.chartsearchai.reference;

/**
 * DrugReferenceSource backed by the bundled DDInter 2.0 dataset (DDI pairs +
 * mechanism + severity), normalized to RxNorm and cross-walked to CIEL.
 * Selected by sourceFormat=ddinter. Fail-safe: any load problem degrades to an
 * empty list, never an exception (the drug-reference feature stays additive).
 */
public class DdiDrugReferenceSource implements DrugReferenceSource {

    static final String CLASSPATH_DEFAULT = "/chartsearchai/ddi-kb-compact.json.gz";

    @Override
    public List<DrugReference> load() {
        // GP-configured path with classpath fallback, mirroring JsonDrugReferenceSource
        return ReferenceDataFiles.loadWithClasspathFallback(
            ChartSearchAiConstants.GP_DDI_DATA_FILE_PATH, CLASSPATH_DEFAULT,
            "DDI knowledge base", DdiDrugReferenceSource::parse);
    }

    // parse(): pair-centric KB -> drug-centric DrugReference entries,
    // interning shared mechanism strings; attach bundled ATC + CIEL aliases.
}
```

It reuses the module's existing conventions: the `ReferenceDataFiles.loadWithClasspathFallback` resolution, a new `GP_DDI_DATA_FILE_PATH` global property, and the fail-safe contract. `DrugReferenceService` gains one branch: `sourceFormat=ddinter` selects this source, everything else is unchanged.

### The bundled data

The source reads one normalized artifact, produced offline by the data project and fully static: `ddi_kb_compact.json` (~19 MB raw, 2 MB gz). It already carries everything the source needs, joined by id:

1. a `mechanisms` table (stored once): text + mechanism categories, keyed by group id;
2. a `drugs` table: name, RxCUI, RxNorm name, DrugBank id, the pre-derived ATC codes (from RxNorm RxClass), and the linked CIEL concepts (code, uuid, name); and
3. an `interactions` list in compact array form (`[drug_a_id, drug_b_id, severity, group_id]`).

The important constraint this respects: **nothing is fetched at runtime.** ATC is derived once, offline, in the data project and bundled as a map, so the module keeps its local-only, no-external-API posture. Refreshing the data is a maintainer re-bundle on the release cycle, exactly as the WHO ATC source already works.

### Mapping to the model

The transform is the one documented in the integration plan: for each drug, group its pairs into `interactions[].{token, atc, note}`. `note` carries severity plus the mechanism text; `aliases` are enriched with RxNorm and CIEL concept names; `atcCodes` come from the bundled map. `ageBands` and `contraindications` stay empty, consistent with the V1 DDI-only scope.

## Two small model additions (optional, additive)

Neither is required for the source to work, and both are backward-compatible (new fields, and the model already ignores unknown properties). We raise them because the data supports them and they improve the feature:

1. **`severity` on `Interaction`.** DDInter classifies every pair (Major / Moderate / Minor / Unknown). A `severity` field would let `DrugSafetyValidator` rank the non-blocking chips rather than flatten severity into prose. Today it lives only inside `note`.
2. **CIEL-concept order matching.** The module matches active orders by ATC. In an OpenMRS chart, orders reference CIEL concepts directly, so a CIEL-concept-keyed match (from the bundled crosswalk) is more precise than the ATC hop for this environment. This could be an optional matcher alongside the ATC one, not a replacement.

## Scale, memory, and a possible interface evolution

With the normalized dataset and shared mechanism strings, `load()` returning the full list is workable. If the maintainers would rather not hold the whole set in memory at all, a natural evolution is an optional indexed lookup on the source (resolve a `DrugReference` by token or RxCUI on demand) so the injector and validator pull only what a query needs. That is a larger change to the consumers, so we mention it as a direction, not a requirement; the normalized-load approach needs no interface change.

## Backward compatibility and safety

- Default behavior is unchanged: `sourceFormat` defaults to `json`, and `ddinter` is opt-in.
- Fail-safe is preserved: a missing or unreadable dataset yields an empty list, so the feature degrades to off rather than breaking the answer path.
- The knowledge-gap principle holds: a drug or pair absent from the dataset is surfaced as a gap by the existing machinery, never as a false "no interaction."

## Testing

Mirror the existing `JsonDrugReferenceSourceTest` for the new source, and extend the `drug-safety-eval.json` set with known-dangerous pairs. The data project already validates these fire at `Major` with real mechanism notes and partner ATC: warfarin × ibuprofen, warfarin × aspirin, simvastatin × clarithromycin, methotrexate × ibuprofen, digoxin × amiodarone, ciprofloxacin × warfarin. A self-contained 16-drug demo file (~130 KB) is available to load through the source in tests without shipping the full dataset.

## Provenance and licensing

The data is DDInter 2.0 (open-access; its published terms were reviewed and permit redistribution with attribution), with RxNorm normalization and the CIEL crosswalk (included with CIEL's maintainer's permission). The data project is MPL 2.0 with the OpenMRS Healthcare Disclaimer, matching this module's licensing, so the bundled artifacts drop in without a license mismatch.

## Suggested rollout

- **2a:** the `DdiDrugReferenceSource` + bundled data + the `ddinter` branch in `DrugReferenceService`. No model change, no consumer change. This is the substance of the PR.
- **2b:** the `severity` field and the CIEL-concept matcher, if the maintainers want them, as follow-ups once 2a lands.

## Open questions for the maintainers

1. Bundle the ~19 MB dataset in the module, or ship a small default and resolve the full set via the GP path (implementer-provided)?
2. Is mechanism-interning-with-`load()` acceptable, or is the indexed-lookup interface evolution worth doing up front?
3. Would you take the `severity` field and the optional CIEL matcher upstream (2b), or keep severity in the note for now?
4. Preferred default scope for a shipped dataset: full, Major+Moderate, or a named formulary (CIEL, WHO EML)?
5. Where should ATC derivation live long term: in the data project's bundled map (current proposal), or would you want a periodic refresh job?
