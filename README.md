# OpenMRS Drug-Drug Interaction Knowledge Base

A ready-to-bundle drug-drug interaction (DDI) knowledge base for OpenMRS. Given two drugs, it answers one question with a citation: do they interact, how seriously, and by what mechanism. It is built entirely from public sources, carries no implementer maintenance burden, and is keyed to the identifiers OpenMRS already uses.

It was built for the Chart Search AI DDI feature, but nothing about it is specific to that module: any OpenMRS component that needs interaction checking can consume it.

## What it is

The knowledge base is a single normalized JSON file, `ddi_knowledge_base.json` (~35 MB). It holds DDInter's two clinical tables, normalized and joined by id: a mechanisms table (each of the 8,234 descriptions stored once), a drugs table, 295,184 drug-drug interaction rows carrying severity and a mechanism reference, and 8,346 drug-disease rows (the conditions a drug is rated against, with their 3,942 descriptions and references stored once). On top of those it carries one **derived** tier, 111,138 condition-mediated chains inferred from the drug-disease rows and kept in their own table so they can never be mistaken for DDInter's ratings. Two things make it usable inside OpenMRS rather than just a data dump:

- Every drug is resolved to an **RxNorm RxCUI**, so a drug named three different ways resolves to one identifier and an interaction is not missed on a spelling difference.
- Every drug is cross-walked to the **CIEL concept dictionary**, so a medication recorded in a patient's chart maps directly to its interaction records.

It works offline. The interaction data is a bundled file, not a live API call, so it runs in low-connectivity settings, which is the deployment reality the design targets.

## What it can be used for inside OpenMRS

- **Interaction checking at the point of prescribing.** When a clinician is about to add a drug, resolve the proposed drug and the patient's current medications to RxCUIs and look up each pair. Return the severity, the mechanism, and the citation.
- **Screening an existing medication list.** Take a patient's active medications (recorded as CIEL concepts), resolve them through `ciel_index.json`, and check every pair among them for interactions already in play.
- **Severity triage and alerting.** The four-level severity (`Major`, `Moderate`, `Minor`, `Unknown`) lets a module decide what to surface loudly, what to note quietly, and what to log.
- **Condition-aware checking.** The drug-disease rows say which conditions a drug is contraindicated in or needs care with (metformin in lactic acidosis, the NRTIs in liver disease). Checked against a patient's condition list, they are contraindication warnings. Checked against each other, they surface pairs DDInter never rated as a pair: stavudine and metformin is `Unknown` as a drug-drug row, but stavudine's liver-disease text names lactic acidosis and metformin is `Major` for lactic acidosis, and the tooling reports that chain as a derived finding.
- **Grounding an AI assistant's answers.** Chart Search AI uses it as a cited knowledge source so an interaction claim is backed by a real record, not a plausible-sounding guess. The same grounding works for any LLM-backed feature.
- **Formulary coverage analysis.** The CIEL crosswalk lets an implementer see, for their own formulary, which drugs have interaction data and which are gaps to handle explicitly.

The governing rule for all of these: when a drug or a pair is not in the knowledge base, that is a knowledge gap to surface, never a silent "no interaction found." The data supports that behavior by being explicit about what it does and does not contain.

## What's inside

| File | What it is |
|---|---|
| `out/ddi_knowledge_base.json` | **The knowledge base** (~35 MB): the canonical source of truth. Normalized: a mechanisms table (8,234, stored once), a drugs table (name, RxCUI, ATC, CIEL), 295,184 interaction rows `[drug_a_id, drug_b_id, severity, group_id]`, 8,346 drug-disease rows `[drug_id, condition, severity, note_id]` with their 3,942 notes stored once, and 111,138 derived rows (an inference tier; see "The record shape"). `build_kb.py` validates it and refreshes the sample. |
| `out/schema.json` | JSON Schema (draft 2020-12) for the knowledge base JSON. |
| `out/sample.json` | A few reconstructed interaction rows for quick inspection. |
| `out/ciel_index.json` | Reverse lookup for module use: a patient's CIEL concept UUID maps to the KB drug(s) to check. |
| `out/ciel_ddinter_coverage_summary.json` | Aggregate CIEL-to-DDInter coverage. |
| `out/rxcui_review.json` | Human-readable record of the RxNorm canonicalization and clinician curation review. |
| `query_kb.py` | Command-line and importable query tool over the knowledge base (see "Asking it questions"). `tests/` exercises it against the built file. |
| `fetch_disease_interactions.py` | The network step that refreshes `src/disease_interactions.jsonl` from DDInter's per-drug drug-disease endpoint (the table is not in DDInter's bulk downloads). |
| `src/` | The build inputs: DDInter facts (`drugs.jsonl`, `interactions.jsonl`, `ddi_mechanisms.json`, `disease_interactions.jsonl`), the RxNorm/RxClass/CIEL fetch results, and the clinician decisions (`curation.json`). `build_kb.py` turns these into the KB above. |
| `dist/chartsearchai-drug-reference-demo.json` | Chart Search AI module format, 16-drug demo (see `docs/INTEGRATION.md`); drug-disease rows become the module's `condition` contraindications. Run `adapt_to_chartsearchai.py full` to generate the full dataset (~180 MB, not committed). |

## The record shape

Tables joined by id, so nothing is duplicated:

```json
{
  "mechanisms": {
    "34": { "text": "Coadministration with potent inhibitors of CYP450 3A4 may significantly increase the plasma concentrations of pitavastatin...", "categories": ["synergistic_effect"] },
    "-1": { "text": null, "categories": [] }
  },
  "drugs": [
    { "id": "DDInter1", "name": "Abacavir", "rxcui": "190521", "rxnorm_name": "abacavir",
      "drugbank_id": "DB01048", "atc": ["J05AF06"],
      "ciel": [ { "code": "103166", "uuid": "103166AAAA…", "name": "Abacavir / lamivudine" } ] }
  ],
  "interactions": [
    ["DDInter1089", "DDInter1479", "Major", "34"]
  ],
  "disease_notes": {
    "1": { "text": "The use of metformin is contraindicated in patients with renal dysfunction...", "references": ["Luft D, Schmulling RM, Eggstein M \"Lactic acidosis in biguanide-treated diabetics: a review of 330 cases.\" Diabetologia 14 (1978): 75-87", "..."] }
  },
  "disease_interactions": [
    ["DDInter1164", "Acidosis, Lactic", "Major", "1"]
  ],
  "derived_interactions": [
    ["DDInter1710", "Liver Diseases", "Major", "412", "DDInter1164", "Acidosis, Lactic", "Major", "1"]
  ]
}
```

An interaction row is `[drug_a_id, drug_b_id, severity, group_id]`: join the ids to `drugs[]` for names/RxCUIs/CIEL, and the `group_id` to `mechanisms` for the description. A pair with no published mechanism references the sentinel group `-1` (null text).

A drug-disease row is `[drug_id, condition, severity, note_id]`: the condition is DDInter's MeSH-style name (`Acidosis, Lactic`, `Liver Diseases`), and the `note_id` joins to `disease_notes` for the description and its citations. DDInter reuses one paragraph across a drug class (the NRTI hepatotoxicity text sits under didanosine, stavudine, and zalcitabine alike), which is why the notes are stored once.

A derived row is `[cause_drug_id, cause_condition, cause_severity, cause_note_id, rated_drug_id, condition, rated_severity, rated_note_id]`, and it is an **inference, not a DDInter rating**. It exists because DDInter never joins its own two tables: stavudine and metformin is `Unknown` as a drug-drug row, yet stavudine's `Liver Diseases` text says lactic acidosis is associated with NRTIs and metformin is `Major` for `Acidosis, Lactic`. A derived row records exactly that chain: a sentence in the cause drug's text says it causes or worsens the condition (whole-word match, a causal cue such as "may cause" or "associated with", and no precaution phrasing such as "in patients with"), and the rated drug carries a row for that condition. Both source rows are cited by note id, so a reader can check the chain. Two drugs merely sharing a precaution (both need care in kidney disease, as 667 drugs do) is deliberately not a chain. `build_kb.py` produces the table with the same matcher `query_kb.py` uses, imported rather than copied, and a test asserts the two agree. A consumer should show derived rows as their own tier, below DDInter's pairwise ratings, and never assign the pair a severity of its own.

**The join key is the RxCUI.** A chart medication resolves CIEL concept to RxCUI (via `ciel_index.json`), and the RxCUI keys into the drugs table. That single key is what ties the patient's data, the drug vocabulary, and the interaction knowledge together.

## Asking it questions

Because the JSON is normalized, answering even a simple question by hand means two joins. `query_kb.py` does the joins and answers the questions a clinician or a module author actually asks, from the command line:

```
python3 query_kb.py pair warfarin aspirin                              # do these two interact? severity and mechanism
python3 query_kb.py check warfarin aspirin simvastatin clarithromycin  # every interacting pair in a medication list
python3 query_kb.py partners warfarin --severity Major                 # a drug's interacting partners, most severe first
python3 query_kb.py drug warfarin                                      # identifiers, ATC, CIEL concepts, partner counts
python3 query_kb.py conditions metformin                               # the conditions a drug is rated against
python3 query_kb.py mechanism 34                                       # a mechanism group's text and categories
python3 query_kb.py search statin                                      # drugs whose name contains a string
```

A drug can be named by its DDInter name, its RxNorm name, or a CIEL concept name, or by identifier with a prefix (`rxcui:11289`, `ciel:86415`, `drugbank:DB00682`, `id:DDInter1951`). Add `--json` to any command for machine-readable output. The same logic is importable (`from query_kb import KB`) for scripts and notebooks, and it needs nothing beyond Python 3.

Two behaviors are deliberate. A misspelled drug gets close-match suggestions rather than a silent empty result, and a pair with no record is reported as a knowledge gap, in the words of the governing rule above, never as "no interaction." A CIEL name that covers a combination product (say, "Acetaminophen / aspirin") resolves to every ingredient it contains, so a question about it checks all of them.

`pair` and `check` also report **derived** findings from the KB's derived tier, kept in a separate, labelled section (see "The record shape" for what a derived row is). For stavudine and metformin the tool shows DDInter's `Unknown` row and then the lactic-acidosis chain with both source rows side by side, saying why they are linked. Shared precautions are not links; `conditions` reports those per drug, for checking against the patient's own condition list.

## How it was made

Three public sources, layered so each does the job it is best at:

- **DDInter 2.0** supplies the interactions: the pair, a severity, and a mechanism description. It is open-access, requires no implementer maintenance, and works offline. The full database (about 302K interactions) was assembled by walking DDInter's interaction groups, since the bulk CSV downloads cover only eight of the fourteen ATC anatomical groups (no cardiovascular, anti-infective, or nervous-system files) and carry no mechanism text. DDInter's drug-disease table was fetched the same way, one request per drug, because it is not in the downloads at all: 8,346 rows across 1,480 drugs, every row with a description and nearly every one with literature or product-label references.
- **RxNorm** (NLM) supplies drug-name normalization. 2,255 of 2,283 drugs resolved to a current RxNorm single-ingredient (`IN`) RxCUI, canonicalized so the key is consistent for joining. Distinct drugs that had been merged onto one identifier were separated under clinician review, and 28 concepts with no safe current mapping (obsolete, low-DDI-relevance items such as vaccines by age band, multivitamins, and IV fluids) were left as explicit gaps (`rxcui` null) rather than assigned a wrong identifier. The canonicalization and every clinician decision are recorded in `out/rxcui_review.json`.
- **CIEL** supplies the OpenMRS bridge. CIEL's own concept-to-RxNorm mappings (from the v2026-07-20 export) link the dictionary a chart uses to the RxCUIs this knowledge base is keyed on. CIEL and KB drugs are matched at the RxNorm ingredient level, so a combination product resolves to its components without falsely bridging unrelated ingredients.

No step requires an implementer to curate drug data by hand, and the build is reproducible and offline. The committed `src/` inputs hold the facts fetched once from DDInter, RxNorm, RxClass, and CIEL, together with the clinician decisions captured as explicit data (`src/curation.json`: 5 separations, 4 remaps, 28 gaps). `build_kb.py` deterministically assembles `ddi_knowledge_base.json` from those inputs: RxNorm base match, canonicalization to the single-ingredient (`IN`) concept, the clinician overrides, the CIEL ingredient-level bridge, and ATC. Because the human decisions are data rather than re-derived, the build reproduces the exact curated knowledge base — confirm with `python3 build_kb.py --check`. Only the one-time acquisition of `src/` (the network fetches from those four sources) lives outside the repo, in the git history.

### Reproducing the build

```
python3 build_kb.py            # src/ -> out/ddi_knowledge_base.json (+ sample, CIEL index)
python3 build_kb.py --check     # verify the rebuild matches the committed KB
python3 -m unittest discover tests       # query the built KB and check every row joins
python3 adapt_to_chartsearchai.py demo   # project into the Chart Search AI module format
python3 fetch_disease_interactions.py    # network: refresh src/disease_interactions.jsonl from DDInter
```

`build_kb.py` is offline and deterministic. Refreshing a source input from its
external service is a separate, network-facing step; two are kept in-repo.
`fetch_disease_interactions.py` walks DDInter's per-drug drug-disease endpoint
(resumable, one request per drug). `derive_atc.py` rebuilds `src/atc_cache.jsonl`
from RxNorm. It must produce
**level-5** ATC substance codes (via RxNorm's `propName=ATC`, e.g. `C09AA03`),
not level-4 subgroups (`C09AA`) — the Chart Search AI validator keys on level-5,
and a level-4 code silently fires a false duplicate-therapy warning on the
patient's own drug. `build_kb.py` enforces this: the build fails if any ATC code
is not level-5, so the fix cannot regress through the pipeline.

## Coverage

| Dimension | Figure |
|---|---|
| Interactions | 295,184 pairs across 2,283 drugs |
| Severity | 50,983 Major · 189,439 Moderate · 12,347 Minor · 42,415 Unknown |
| Mechanism text | 252,766 interactions (86%) |
| Drug-disease rows | 8,346 across 1,480 drugs (64.8%) and 470 conditions; 3,691 Major · 4,572 Moderate · 83 Minor |
| Drug-disease text | 8,346 / 8,346 rows carry a description; 8,315 carry references |
| Derived tier | 111,138 chains linking 97,493 drug pairs through 185 conditions (923 cause drugs, 1,318 rated drugs) |
| Derived tier vs DDInter's pairwise rows | 65,406 of those pairs DDInter does not list; 5,021 it rates `Unknown`; 27,066 it already rates |
| RxNorm normalization | 2,255 / 2,283 drugs to a current ingredient RxCUI (28 obsolete, low-relevance concepts left as explicit gaps) |
| CIEL bridge | 1,986 / 2,283 KB drugs (87%) carry a CIEL concept |
| CIEL formulary overlap | 4,258 of 7,615 RxNorm-mapped CIEL drugs (55.9%) have interaction data |

The 55.9% is measured at the ingredient level: a naive exact-RxCUI match reports only 23%, because CIEL maps concepts to product-level RxCUIs while this knowledge base is ingredient-level, so both sides must be reduced to their RxNorm ingredient before matching.

### Coverage by ATC group

DDInter's bulk downloads offer files for only eight of the fourteen ATC anatomical groups, leaving out cardiovascular, anti-infective, and nervous-system drugs among others. This knowledge base was assembled by walking DDInter's interaction groups instead, so every ATC group is covered. The table is the output of `python3 query_kb.py coverage`; regenerate it rather than editing it.

| ATC | Group | Drugs | Interaction rows | In DDInter's bulk downloads |
|---|---|---|---|---|
| A | Alimentary tract and metabolism | 248 | 58,386 | yes |
| B | Blood and blood forming organs | 117 | 18,563 | yes |
| C | Cardiovascular system | 205 | 66,182 | no |
| D | Dermatologicals | 189 | 31,880 | yes |
| G | Genito-urinary system and sex hormones | 112 | 27,147 | no |
| H | Systemic hormonal preparations | 61 | 15,625 | yes |
| J | Anti-infectives for systemic use | 239 | 52,622 | no |
| L | Antineoplastic and immunomodulating agents | 345 | 97,492 | yes |
| M | Musculo-skeletal system | 65 | 18,996 | no |
| N | Nervous system | 291 | 102,180 | no |
| P | Antiparasitic products | 39 | 6,694 | yes |
| R | Respiratory system | 145 | 32,050 | yes |
| S | Sensory organs | 209 | 38,357 | no |
| V | Various | 71 | 9,359 | yes |

A row counts toward every group either drug belongs to. 444 drugs carry no ATC code (RxNorm publishes none for them), so they appear in no group here while still carrying their interactions.

## What it is not

Being honest about the edges matters more here than in most data, because the consequences are clinical.

- **It is not a management guide.** DDInter's text describes the mechanism and effect; it does not expose a discrete management recommendation, so `management` is null rather than filled with invented guidance.
- **It is not complete in either direction.** About 14% of interactions have no written mechanism (DDInter lists the pair without a description), and 296 drugs that DDInter covers have no CIEL concept (recent approvals and supplements, mostly), while 44% of CIEL's RxNorm-mapped drugs have no DDInter interaction data (largely vaccines, venoms, and herbal preparations DDInter does not carry). A module must treat any absence as a gap, not a clearance.
- **The derived tier is an inference, not a DDInter rating.** A derived row links two drugs only when a causal sentence in one drug's drug-disease text names a condition the other is rated for, and it cites both source rows. It never assigns the pair a severity of its own, and the matcher is a text heuristic: it will miss chains phrased in ways it does not recognize and will occasionally link through a mention that reads as causal but is not. A consumer that surfaces derived rows should show them as their own tier, below DDInter's pairwise ratings, and label them as derived.
- **Drug-food interactions are not included.** DDInter also publishes a drug-food table (metformin and alcohol, for example, which carries the only management text DDInter has). It is not ingested here.
- **It is not a government-agency product.** DDInter is an academic database, peer-reviewed by pharmacists. That is a governance consideration for clinical deployment, not a data defect, and it is the one open sourcing question the design flags.
- **A few RxCUIs are shared by design.** Drug RxCUIs are canonicalized to the RxNorm ingredient, and a clinician reviewed the cases where more than one drug shared an identifier. Genuinely distinct drugs that had been merged (for example the trastuzumab antibody-drug conjugates, or methscopolamine and scopolamine) were separated. The ~29 that remain shared are deliberate: stereoisomer and racemate pairs (omeprazole and esomeprazole, atropine and hyoscyamine) and prodrug/active-metabolite pairs, which share an interaction profile, plus formulation, salt, and vaccine-naming variants. The full review trail is in `out/rxcui_review.json`.

## Provenance and license

The data comes from DDInter 2.0 (https://ddinter2.scbdd.com/) and the CIEL concept dictionary (https://app.openconceptlab.org/#/orgs/CIEL/sources/CIEL/), with drug-name normalization by NLM RxNorm. Full attribution and citations are in [ATTRIBUTION.md](ATTRIBUTION.md).

This repository is licensed under the **Mozilla Public License 2.0 with the OpenMRS Healthcare Disclaimer**, matching OpenMRS's own licensing. See [LICENSE](LICENSE) and [HEALTHCARE_DISCLAIMER.md](HEALTHCARE_DISCLAIMER.md). The disclaimer is not boilerplate here: this is decision support, coverage is incomplete, and a missing pair is a knowledge gap rather than a safety guarantee.
