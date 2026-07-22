# OpenMRS Drug-Drug Interaction Knowledge Base

A ready-to-bundle drug-drug interaction (DDI) knowledge base for OpenMRS. Given two drugs, it answers one question with a citation: do they interact, how seriously, and by what mechanism. It is built entirely from public sources, carries no implementer maintenance burden, and is keyed to the identifiers OpenMRS already uses.

It was built for the Chart Search AI DDI feature, but nothing about it is specific to that module: any OpenMRS component that needs interaction checking can consume it.

## What it is

The knowledge base is a single normalized JSON file, `ddi_kb_compact.json`, shipped as a ~2 MB compressed `.gz` as its distributable form. It holds three tables joined by id: a mechanisms table (each of the 8,234 descriptions stored once), a drugs table, and 295,184 interaction rows carrying severity and a mechanism reference. Two things make it usable inside OpenMRS rather than just a data dump:

- Every drug is resolved to an **RxNorm RxCUI**, so a drug named three different ways resolves to one identifier and an interaction is not missed on a spelling difference.
- Every drug is cross-walked to the **CIEL concept dictionary**, so a medication recorded in a patient's chart maps directly to its interaction records.

It works offline. The interaction data is a bundled file, not a live API call, so it runs in low-connectivity settings, which is the deployment reality the design targets.

## What it can be used for inside OpenMRS

- **Interaction checking at the point of prescribing.** When a clinician is about to add a drug, resolve the proposed drug and the patient's current medications to RxCUIs and look up each pair. Return the severity, the mechanism, and the citation.
- **Screening an existing medication list.** Take a patient's active medications (recorded as CIEL concepts), resolve them through `ciel_index.json`, and check every pair among them for interactions already in play.
- **Severity triage and alerting.** The four-level severity (`Major`, `Moderate`, `Minor`, `Unknown`) lets a module decide what to surface loudly, what to note quietly, and what to log.
- **Grounding an AI assistant's answers.** Chart Search AI uses it as a cited knowledge source so an interaction claim is backed by a real record, not a plausible-sounding guess. The same grounding works for any LLM-backed feature.
- **Formulary coverage analysis.** The CIEL crosswalk lets an implementer see, for their own formulary, which drugs have interaction data and which are gaps to handle explicitly.

The governing rule for all of these: when a drug or a pair is not in the knowledge base, that is a knowledge gap to surface, never a silent "no interaction found." The data supports that behavior by being explicit about what it does and does not contain.

## What's inside

| File | What it is |
|---|---|
| `out/ddi_kb_compact.json.gz` | **The knowledge base** (compressed final form, ~2 MB). Normalized: a mechanisms table (8,234, stored once), a drugs table (name, RxCUI, ATC, CIEL), and 295,184 interaction rows `[drug_a_id, drug_b_id, severity, group_id]`. |
| `out/ddi_kb_compact.json` | The same, uncompressed (~19 MB): the canonical, editable source of truth. `build_kb.py` validates it and rebuilds the `.gz`. |
| `out/schema.json` | JSON Schema (draft 2020-12) for the compact format. |
| `out/sample.json` | A few reconstructed interaction rows for quick inspection. |
| `out/ciel_index.json` | Reverse lookup for module use: a patient's CIEL concept UUID maps to the KB drug(s) to check. |
| `out/ciel_rxnorm_crosswalk.json` | CIEL Drug concept (code, UUID, name) to RxCUI(s). |
| `out/ciel_ddinter_coverage_summary.json` | Aggregate CIEL-to-DDInter coverage. |
| `out/rxcui_review.json` | Record of the RxNorm canonicalization and clinician curation decisions. |
| `dist/chartsearchai-drug-reference-demo.json` | Chart Search AI module format, 16-drug demo (see `docs/INTEGRATION.md`). |
| `dist/chartsearchai-drug-reference.json.gz` | Chart Search AI module format, full dataset. |

## The record shape

Three tables joined by id, so nothing is duplicated:

```json
{
  "mechanisms": {
    "34": { "text": "Coadministration with potent inhibitors of CYP450 3A4 may significantly increase the plasma concentrations of pitavastatin...", "categories": ["synergistic_effect"] },
    "-1": { "text": null, "categories": [] }
  },
  "drugs": [
    { "id": "DDInter1", "name": "Abacavir", "rxcui": "190521", "rxnorm_name": "abacavir",
      "drugbank_id": "DB01048", "atc": ["J05AR", "J05AF"],
      "ciel": [ { "code": "103166", "uuid": "103166AAAA…", "name": "Abacavir / lamivudine" } ] }
  ],
  "interactions": [
    ["DDInter1089", "DDInter1479", "Major", "34"]
  ]
}
```

An interaction row is `[drug_a_id, drug_b_id, severity, group_id]`: join the ids to `drugs[]` for names/RxCUIs/CIEL, and the `group_id` to `mechanisms` for the description. A pair with no published mechanism references the sentinel group `-1` (null text).

**The join key is the RxCUI.** A chart medication resolves CIEL concept to RxCUI (via `ciel_index.json`), and the RxCUI keys into the drugs table. That single key is what ties the patient's data, the drug vocabulary, and the interaction knowledge together.

## How it was made

Three public sources, layered so each does the job it is best at:

- **DDInter 2.0** supplies the interactions: the pair, a severity, and a mechanism description. It is open-access, requires no implementer maintenance, and works offline. The full database (about 302K interactions) was assembled by walking DDInter's interaction groups, since the bulk CSV download carries only about half the pairs and no mechanism text.
- **RxNorm** (NLM) supplies drug-name normalization. 2,255 of 2,283 drugs resolved to a current RxNorm single-ingredient (`IN`) RxCUI, canonicalized so the key is consistent for joining. Distinct drugs that had been merged onto one identifier were separated under clinician review, and 28 concepts with no safe current mapping (obsolete, low-DDI-relevance items such as vaccines by age band, multivitamins, and IV fluids) were left as explicit gaps (`rxcui` null) rather than assigned a wrong identifier. The canonicalization and every clinician decision are recorded in `out/rxcui_review.json`.
- **CIEL** supplies the OpenMRS bridge. CIEL's own concept-to-RxNorm mappings (from the v2026-07-20 export) link the dictionary a chart uses to the RxCUIs this knowledge base is keyed on. CIEL and KB drugs are matched at the RxNorm ingredient level, so a combination product resolves to its components without falsely bridging unrelated ingredients.

No step requires an implementer to curate drug data by hand. The canonical source of truth is `ddi_kb_compact.json`; `build_kb.py` validates it (referential integrity plus shape) and emits the compressed final form and a sample, and `adapt_to_chartsearchai.py` projects it into the Chart Search AI module format. The one-time acquisition-and-curation pipeline that produced the canonical data — the DDInter group walk, RxNorm normalization and canonicalization, the clinician review, the CIEL crosswalk, and ATC derivation — is preserved in the git history and summarized in `out/rxcui_review.json`; because it embeds human clinical decisions, the compact file is the curated source of record rather than a rebuild output.

## Coverage

| Dimension | Figure |
|---|---|
| Interactions | 295,184 pairs across 2,283 drugs |
| Severity | 50,983 Major · 189,439 Moderate · 12,347 Minor · 42,415 Unknown |
| Mechanism text | 252,766 interactions (86%) |
| RxNorm normalization | 2,255 / 2,283 drugs to a current ingredient RxCUI (28 obsolete, low-relevance concepts left as explicit gaps) |
| CIEL bridge | 1,986 / 2,283 KB drugs (87%) carry a CIEL concept |
| CIEL formulary overlap | 4,258 of 7,615 RxNorm-mapped CIEL drugs (55.9%) have interaction data |

The 55.9% is measured at the ingredient level: a naive exact-RxCUI match reports only 23%, because CIEL maps concepts to product-level RxCUIs while this knowledge base is ingredient-level, so both sides must be reduced to their RxNorm ingredient before matching.

## What it is not

Being honest about the edges matters more here than in most data, because the consequences are clinical.

- **It is not a management guide.** DDInter's text describes the mechanism and effect; it does not expose a discrete management recommendation, so `management` is null rather than filled with invented guidance.
- **It is not complete in either direction.** About 14% of interactions have no written mechanism (DDInter lists the pair without a description), and 296 drugs that DDInter covers have no CIEL concept (recent approvals and supplements, mostly), while 44% of CIEL's RxNorm-mapped drugs have no DDInter interaction data (largely vaccines, venoms, and herbal preparations DDInter does not carry). A module must treat any absence as a gap, not a clearance.
- **It is not a government-agency product.** DDInter is an academic database, peer-reviewed by pharmacists. That is a governance consideration for clinical deployment, not a data defect, and it is the one open sourcing question the design flags.
- **A few RxCUIs are shared by design.** Drug RxCUIs are canonicalized to the RxNorm ingredient, and a clinician reviewed the cases where more than one drug shared an identifier. Genuinely distinct drugs that had been merged (for example the trastuzumab antibody-drug conjugates, or methscopolamine and scopolamine) were separated. The ~29 that remain shared are deliberate: stereoisomer and racemate pairs (omeprazole and esomeprazole, atropine and hyoscyamine) and prodrug/active-metabolite pairs, which share an interaction profile, plus formulation, salt, and vaccine-naming variants. The full review trail is in `out/rxcui_review.json`.

## Provenance and license

The data comes from DDInter 2.0 (https://ddinter2.scbdd.com/) and the CIEL concept dictionary (https://app.openconceptlab.org/#/orgs/CIEL/sources/CIEL/), with drug-name normalization by NLM RxNorm. Full attribution and citations are in [ATTRIBUTION.md](ATTRIBUTION.md).

This repository is licensed under the **Mozilla Public License 2.0 with the OpenMRS Healthcare Disclaimer**, matching OpenMRS's own licensing. See [LICENSE](LICENSE) and [HEALTHCARE_DISCLAIMER.md](HEALTHCARE_DISCLAIMER.md). The disclaimer is not boilerplate here: this is decision support, coverage is incomplete, and a missing pair is a knowledge gap rather than a safety guarantee.
