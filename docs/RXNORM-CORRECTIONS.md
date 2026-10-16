# RxNorm ingredient identity corrections (issue #6)

On 2026-10-16, the three frozen name-normalization results below were checked
against NLM RxNav. Each replacement is a current, unsuppressed ingredient
(`tty=IN`, `suppress=N`). Its DrugBank cross-reference agrees with the DrugBank
identifier already attached to the DDInter drug. These are source-verified
corrections submitted for review, not a record of clinician approval; the
existing clinician decisions in `src/curation.json` are unchanged.

| DDInter drug | Previous RxCUI / substance | Correct RxCUI / RxNorm name | Retained DrugBank ID | ATC |
|---|---|---|---|---|
| `DDInter1724` Sulfamethoxazole | `10178` sulfamethazine | [`10180` sulfamethoxazole](https://rxnav.nlm.nih.gov/REST/rxcui/10180/allProperties.json?prop=all) | `DB01015` | `J01EC01` |
| `DDInter362` Chlorpheniramine | `1310122` chlorine | [`2400` chlorpheniramine](https://rxnav.nlm.nih.gov/REST/rxcui/2400/allProperties.json?prop=all) | `DB01114` | `R06AB04` |
| `DDInter1171` Methionine | `1426463` N-acetylmethionine | [`6837` methionine](https://rxnav.nlm.nih.gov/REST/rxcui/6837/allProperties.json?prop=all) | `DB00134` | `V03AB26` |

The corrections are in `src/rxnorm.jsonl`, where the wrong identifiers first
entered the build. The existing singleton ingredient-cache entries already
cover the replacement RxCUIs. The frozen CIEL v2026-07-20 crosswalk supplies the
correct bridges, including Sulfamethoxazole `84471`, Chlorphenamine `913`, and
Methionine `79692`; rebuilding regenerates the reverse index. The old
sulfamethazine and chlorine concepts must no longer resolve to these DDInter
rows.

## Enrichment source records

Only the three replacement RxCUIs were fetched; unrelated cached results were
retained. Level-5 ATC codes come from the same endpoint `derive_atc.py` uses:

- [10180 ATC](https://rxnav.nlm.nih.gov/REST/rxcui/10180/property.json?propName=ATC)
- [2400 ATC](https://rxnav.nlm.nih.gov/REST/rxcui/2400/property.json?propName=ATC)
- [6837 ATC](https://rxnav.nlm.nih.gov/REST/rxcui/6837/property.json?propName=ATC)

The WHO ATC index corroborates [sulfamethoxazole J01EC01](https://atcddd.fhi.no/atc_ddd_index/?code=J01EC01&showdescription=no),
[chlorphenamine R06AB04](https://atcddd.fhi.no/atc_ddd_index/?code=R06AB04&showdescription=no),
and [methionine V03AB26](https://atcddd.fhi.no/atc_ddd_index/?code=V03AB26&showdescription=no).

Brand names come from the existing fetcher's related-BN endpoint:

- [10180 brands](https://rxnav.nlm.nih.gov/REST/rxcui/10180/related.json?tty=BN)
- [2400 brands](https://rxnav.nlm.nih.gov/REST/rxcui/2400/related.json?tty=BN)
- [6837 brands](https://rxnav.nlm.nih.gov/REST/rxcui/6837/related.json?tty=BN)

The raw fetched names were passed through `fetch_brand_names.py --refilter`.
Its existing dictionary rule excludes `Aller-Chlor` and `Tannic-12 S` for
`2400`; `src/brand_names_excluded.json` retains that provenance. Combination
brands intentionally fan out to all related ingredients: Bactrim and Sulfatrim
now reach sulfamethoxazole as well as trimethoprim, and methionine's returned
brands include amino-acid mixtures. A brand is not a claim of a single
ingredient.

The offline build now rejects an ingredient missing from either enrichment
cache. An explicit cached empty list still means the source returned no data
and is valid. `tests/test_build_kb.py` exercises the actual build and query
paths, including wrong-substance exclusion and CIEL reverse lookup.
