# OpenMRS Drug-Drug Interaction Knowledge Base

A ready-to-bundle drug-drug interaction (DDI) knowledge base for OpenMRS. Given two drugs, it answers one question with a citation: do they interact, how seriously, and by what mechanism. It is built entirely from public sources, carries no implementer maintenance burden, and is keyed to the identifiers OpenMRS already uses.

It was built for the Chart Search AI DDI feature, but nothing about it is specific to that module: any OpenMRS component that needs interaction checking can consume it.

## What it is

The knowledge base is a set of JSON files. The primary artifact is a single file of 295,184 interacting drug pairs, each carrying a severity, a mechanism description where one exists, and full provenance back to its source. Two things make it usable inside OpenMRS rather than just a data dump:

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
| `out/ddi_knowledge_base_enriched.json.gz` | **The knowledge base.** 2,283 drugs and 295,184 interactions, each with severity, mechanism, mechanism categories, RxCUI, and CIEL concepts. ~19 MB gzipped, ~272 MB open (over GitHub's 100 MB limit, so it is stored compressed; `gunzip` to use). |
| `out/ciel_index.json` | Reverse lookup for module use: a patient's CIEL concept UUID maps to the KB drug(s) to check. |
| `out/interaction.schema.json` | JSON Schema (draft 2020-12) for one interaction record. |
| `out/ddi_knowledge_base.json` | The bulk-CSV-only subset (160,235 pairs, severity only), kept for comparison. |
| `out/ddi_mechanisms.json` | The 8,466 DDInter mechanism descriptions on their own. |
| `out/ciel_rxnorm_crosswalk.json` | CIEL Drug concept (code, UUID, name) to RxCUI(s). |
| `out/ciel_ddinter_coverage_summary.json` | Aggregate CIEL-to-DDInter coverage. |
| `out/enriched_sample.json` | A handful of worked records for quick inspection. |

## The record shape

```json
{
  "id": "DDInter1089__DDInter1479",
  "drug_a": { "ddinter_id": "DDInter1089", "name": "Lopinavir", "drugbank_id": "DB01601", "rxcui": "195088" },
  "drug_b": { "ddinter_id": "DDInter1479", "name": "Pitavastatin", "drugbank_id": "DB08860", "rxcui": "861634" },
  "severity": "Major",
  "mechanism": "Coadministration with lopinavir-ritonavir may significantly increase the plasma concentrations of pitavastatin...",
  "management": null,
  "mechanism_categories": ["synergistic_effect"],
  "source": "DDInter 2.0",
  "source_group_id": "34",
  "source_url": "https://ddinter2.scbdd.com/server/inter-detail/34/",
  "citation": "Xiong G, et al. DDInter 2.0. Nucleic Acids Research. 2025;53(D1):D1356-D1364."
}
```

The top-level `drugs[]` list carries the richer per-drug detail: `rxcui`, `rxnorm_name`, how the RxNorm match was made (`rxcui_match`), and the linked `ciel_concepts`.

**The join key is the RxCUI.** A chart medication resolves CIEL concept to RxCUI (via `ciel_index.json`), and the RxCUI keys into the interaction records. That single key is what ties the patient's data, the drug vocabulary, and the interaction knowledge together.

## How it was made

Three public sources, layered so each does the job it is best at:

- **DDInter 2.0** supplies the interactions: the pair, a severity, and a mechanism description. It is open-access, requires no implementer maintenance, and works offline. The full database (about 302K interactions) was assembled by walking DDInter's interaction groups, since the bulk CSV download carries only about half the pairs and no mechanism text.
- **RxNorm** (NLM) supplies drug-name normalization. All 2,283 drugs resolved to an RxCUI, and each is then canonicalized to its RxNorm single-ingredient (`IN`) concept so the key is consistent for joining. Each drug records how it matched (`rxcui_match`) and its pre-canonical value (`rxcui_original`), so the work is auditable. The residual cases that cannot be auto-resolved (stereoisomer pairs that share an ingredient concept, salts, and flagged approximate matches) are listed in `out/rxcui_review.json` for review rather than guessed.
- **CIEL** supplies the OpenMRS bridge. CIEL's own concept-to-RxNorm mappings (from the v2026-07-20 export) link the dictionary a chart uses to the RxCUIs this knowledge base is keyed on. CIEL and KB drugs are matched at the RxNorm ingredient level, so a combination product resolves to its components without falsely bridging unrelated ingredients.

No step requires an implementer to curate drug data by hand. The sources update outside the implementer's control; refreshing the bundle is a maintainer re-run on the release cycle. The build scripts (`enrich.py`, `build_enriched.py`, `rxnorm.py`, `ciel_crosswalk.py`, `ciel_reconcile.py`, `ciel_coverage.py`, `integrate_ciel.py`) reproduce every file. The CIEL crosswalk can be regenerated with the OCL CLI or the OCL export API and a token; no token or raw export is stored here.

## Coverage

| Dimension | Figure |
|---|---|
| Interactions | 295,184 pairs across 2,283 drugs |
| Severity | 50,983 Major · 189,439 Moderate · 12,347 Minor · 42,415 Unknown |
| Mechanism text | 252,766 interactions (86%) |
| RxNorm normalization | 2,283 / 2,283 drugs (100%) |
| CIEL bridge | 1,987 / 2,283 KB drugs (87%) carry a CIEL concept |
| CIEL formulary overlap | 4,258 of 7,615 RxNorm-mapped CIEL drugs (55.9%) have interaction data |

The 55.9% is measured at the ingredient level: a naive exact-RxCUI match reports only 23%, because CIEL maps concepts to product-level RxCUIs while this knowledge base is ingredient-level, so both sides must be reduced to their RxNorm ingredient before matching.

## What it is not

Being honest about the edges matters more here than in most data, because the consequences are clinical.

- **It is not a management guide.** DDInter's text describes the mechanism and effect; it does not expose a discrete management recommendation, so `management` is null rather than filled with invented guidance.
- **It is not complete in either direction.** About 14% of interactions have no written mechanism (DDInter lists the pair without a description), and 296 drugs that DDInter covers have no CIEL concept (recent approvals and supplements, mostly), while 44% of CIEL's RxNorm-mapped drugs have no DDInter interaction data (largely vaccines, venoms, and herbal preparations DDInter does not carry). A module must treat any absence as a gap, not a clearance.
- **It is not a government-agency product.** DDInter is an academic database, peer-reviewed by pharmacists. That is a governance consideration for clinical deployment, not a data defect, and it is the one open sourcing question the design flags.
- **A few RxCUIs remain ambiguous.** Drug RxCUIs are canonicalized to the RxNorm ingredient, but about 30 concepts are shared by more than one drug because RxNorm models them that way (stereoisomers such as omeprazole and esomeprazole, or vaccine naming variants). These are flagged in `out/rxcui_review.json`; a consuming module should treat them as needing clinical review rather than as clean one-to-one keys.

## Provenance and license

The data comes from DDInter 2.0 (https://ddinter2.scbdd.com/) and the CIEL concept dictionary (https://app.openconceptlab.org/#/orgs/CIEL/sources/CIEL/), with drug-name normalization by NLM RxNorm. Full attribution and citations are in [ATTRIBUTION.md](ATTRIBUTION.md).

This repository is licensed under the **Mozilla Public License 2.0 with the OpenMRS Healthcare Disclaimer**, matching OpenMRS's own licensing. See [LICENSE](LICENSE) and [HEALTHCARE_DISCLAIMER.md](HEALTHCARE_DISCLAIMER.md). The disclaimer is not boilerplate here: this is decision support, coverage is incomplete, and a missing pair is a knowledge gap rather than a safety guarantee.
