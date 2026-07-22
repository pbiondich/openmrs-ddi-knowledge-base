# Proposal: a DDInter-backed pluggable drug-reference source

*Draft for the `openmrs-module-chartsearchai` maintainers. Companion to the data project at [openmrs-ddi-knowledge-base](https://github.com/pbiondich/openmrs-ddi-knowledge-base) and its [integration plan](./INTEGRATION.md).*

## What this proposes

A new `DrugReferenceSource` implementation, `DdiDrugReferenceSource`, selected by `chartsearchai.drugReference.sourceFormat=ddinter`, that backs the drug-reference feature with the full DDInter 2.0 interaction set instead of the hand-curated `drug-reference.json` seed. It reads a single normalized dataset (`ddi_knowledge_base.json`, a plain ~19 MB JSON) that the data project publishes. It changes no existing behavior: `json` stays the default, and this is one more opt-in adapter behind the seam ADR Decision 24 already established.

The motivation is the problem the original Chart Search AI spec set out to solve: the curated seed covers a handful of drugs and returns nothing for the rest, and it pushes curation onto implementers. A public-source dataset removes both. DDInter is open-access, offline-capable, and maintenance-free; RxNorm and CIEL supply the identifiers the module already reasons over.

## The dataset the source reads

The data project ships a normalized artifact designed to be consumed directly. It has three tables joined by id, so nothing is duplicated: mechanisms are stored once, drugs once, and interactions are array rows that reference both.

```json
{
  "metadata": { "shape": { "drugs": 2283, "mechanisms": 8234, "interactions": 295184 } },
  "mechanisms": {
    "3900": { "text": "Coadministration with potent inhibitors of CYP450 3A4 may significantly increase the plasma concentrations of ivosidenib...", "categories": ["metabolism"] },
    "-1":   { "text": null, "categories": [] }
  },
  "drugs": [
    { "id": "DDInter1", "name": "Abacavir", "rxcui": "190521", "rxnorm_name": "abacavir",
      "drugbank_id": "DB01048", "atc": ["J05AR", "J05AF"],
      "ciel": [ { "code": "103166", "uuid": "103166AAAA…", "name": "Abacavir / lamivudine" } ] }
  ],
  "interactions": [
    ["DDInter1000", "DDInter1008", "Major", "3900"],
    ["DDInter1000", "DDInter1001", "Moderate", "894"]
  ]
}
```

Three properties of this shape matter for the source:
- **Mechanisms are shared, not inlined.** An interaction row carries a `group_id`; the text lives once in `mechanisms`. There are 8,234 mechanisms behind 295,184 pairs, so the source loads the table once and lets every note point at the same string.
- **Everything the model needs is pre-computed and offline.** ATC codes (derived from RxNorm RxClass), RxNorm names, and CIEL concepts are already on each drug. The source does no network calls, which keeps the module local-only.
- **Gaps are in-band.** A pair with no published mechanism references the sentinel group `-1` (null text). The source renders that as a severity-only note; it never invents one.

## The source

```java
package org.openmrs.module.chartsearchai.reference;

/**
 * DrugReferenceSource backed by the normalized DDInter 2.0 dataset
 * (ddi_knowledge_base.json): a mechanisms table, a drugs table (name, RxCUI, ATC,
 * CIEL), and interaction rows referencing both. Selected by sourceFormat=ddinter.
 * Fail-safe: any load problem degrades to an empty list, never an exception.
 */
public class DdiDrugReferenceSource implements DrugReferenceSource {

    static final String CLASSPATH_DEFAULT = "/chartsearchai/ddi-knowledge-base.json";

    @Override
    public List<DrugReference> load() {
        // GP path with classpath fallback, mirroring JsonDrugReferenceSource
        return ReferenceDataFiles.loadWithClasspathFallback(
            ChartSearchAiConstants.GP_DDI_DATA_FILE_PATH, CLASSPATH_DEFAULT,
            "DDI knowledge base", DdiDrugReferenceSource::parse);
    }

    // parse():
    //   1. read mechanisms{} and drugs[] into maps (mechanism text interned here)
    //   2. group interaction rows by drug
    //   3. build one DrugReference per drug:
    //        id/name/atcCodes/aliases from the drugs table,
    //        interactions[] = {token: partner name, atc: partner ATC,
    //                          note: severity + mechanisms[groupId].text (shared)}
}
```

It reuses the module's conventions exactly: the `ReferenceDataFiles.loadWithClasspathFallback` resolution, a new `GP_DDI_DATA_FILE_PATH` global property, and the fail-safe contract. `DrugReferenceService` gains one branch, `sourceFormat=ddinter`, and nothing else changes.

### Mapping the tables to `DrugReference`

| `DrugReference` field | From the knowledge base |
|---|---|
| `id` | drug `rxcui` (fallback `id`) |
| `name` | drug `name` |
| `aliases` | `name` + `rxnorm_name` + each `ciel[].name`, lowercased |
| `atcCodes` | drug `atc[]` (pre-derived) |
| `interactions[].token` | partner drug's `name` |
| `interactions[].atc` | partner drug's first `atc` |
| `interactions[].note` | interaction `severity` + `mechanisms[group_id].text` |
| `ageBands`, `contraindications` | empty (out of V1 scope) |
| `source` | `"DDInter 2.0 (via openmrs-ddi-knowledge-base)"` |

Because the interaction rows are symmetric drug references, each pair contributes to both drugs' entries at build time, which is exactly what the validator's from-either-side matching expects.

## Two model additions the data already supports (optional, additive)

Neither is required for the source to work, and both are backward-compatible. We raise them because the knowledge base already carries the fields:

1. **`severity` on `Interaction`.** Severity is a first-class column on every interaction row (`Major` / `Moderate` / `Minor` / `Unknown`). Surfacing it as a field would let `DrugSafetyValidator` rank the non-blocking chips rather than fold severity into prose. Today it would only live inside `note`.
2. **CIEL-concept order matching.** Each drug carries its CIEL concepts (code, uuid, name). Since an OpenMRS chart records orders as CIEL concepts, a CIEL-concept-keyed match is more precise than the ATC hop for this environment. It could be an optional matcher alongside the existing ATC one, not a replacement.

## Memory and scale

Loading the normalized dataset and sharing mechanism strings keeps `load()` returning the full list workable: the in-memory note cost is bounded by the 8,234 unique mechanisms, not the 295,184 pairs. For comparison, expanding the same data into the flat drug-centric `drug-reference.json` format inlines the mechanism on every pair and reaches about 180 MB, which is why the source reads the normalized form and expands in memory instead. If the maintainers would rather not hold the whole set at all, a natural evolution is an optional indexed lookup on the source (resolve by token or RxCUI on demand); that is a larger change to the consumers, so we offer it as a direction, not a requirement.

## Backward compatibility and safety

- Default behavior is unchanged: `sourceFormat` defaults to `json`; `ddinter` is opt-in.
- Fail-safe is preserved: a missing or unreadable dataset yields an empty list, so the feature degrades to off rather than breaking the answer path.
- The knowledge-gap principle holds: a drug or pair absent from the dataset is surfaced as a gap by the existing machinery, never as a false "no interaction," and a pair present but without a mechanism renders as a severity-only note.

## Testing

Mirror the existing `JsonDrugReferenceSourceTest` for the new source, and extend `drug-safety-eval.json` with known-dangerous pairs. The data project already validates these fire at `Major` with real mechanism notes and partner ATC: warfarin × ibuprofen, warfarin × aspirin, simvastatin × clarithromycin, methotrexate × ibuprofen, digoxin × amiodarone, ciprofloxacin × warfarin. A self-contained 16-drug demo dataset (~130 KB) is available to load through the source in tests without shipping the full set.

## Provenance and licensing

The data is DDInter 2.0 (open-access; its published terms were reviewed and permit redistribution with attribution), with RxNorm normalization and the CIEL crosswalk (included with CIEL's maintainer's permission). The data project is MPL 2.0 with the OpenMRS Healthcare Disclaimer, matching this module, so the bundled artifact drops in without a license mismatch.

## Suggested rollout

- **2a:** the `DdiDrugReferenceSource`, the bundled `ddi-knowledge-base.json`, and the `ddinter` branch in `DrugReferenceService`. No model change, no consumer change. This is the substance of the PR.
- **2b:** the `severity` field and the CIEL-concept matcher, if wanted, as follow-ups once 2a lands.

## Open questions for the maintainers

1. Bundle the ~19 MB dataset in the module, or ship a small default and resolve the full set via the GP path?
2. Is the normalized-load approach acceptable, or is the indexed-lookup interface evolution worth doing up front?
3. Would you take the `severity` field and the optional CIEL matcher upstream (2b)?
4. Preferred default scope for the shipped dataset: full, Major+Moderate, or a named formulary (CIEL, WHO EML)?
5. The published dataset is a plain ~19 MB JSON. Bundle it as-is, or would you rather compress it in the module jar (the reader would then need to decompress)?
