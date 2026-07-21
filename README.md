# DDI Knowledge Base (JSON) for Chart Search AI

This is a JSON build of the drug-drug interaction data behind the Chart Search AI DDI spec. The point was to take the layered public-source design on paper and see what the data actually gives us once you go and pull it. A few things turned out to be different from what the spec assumes, so I've written those down here rather than burying them.

The short version: the primary interaction source (DDInter 2.0) converts cleanly to JSON, the mechanism text is real and citable, and nothing here needs an implementer to hand-curate anything. The gaps are about coverage numbers and about one field the spec expects that DDInter doesn't really expose. Details below.

## What's in here

All data lives in `out/`. Everything was generated on 2026-07-21 from DDInter 2.0; no field is hand-written.

| File | What it is | Size |
|---|---|---|
| `ddi_knowledge_base_enriched.json.gz` | **The primary knowledge base.** 2,283 drugs and 295,184 unique interaction pairs, each with severity, mechanism text, and mechanism-category flags. Gzipped (~17 MB) because it decompresses to ~256 MB, over GitHub's 100 MB file limit; `gunzip` it to get the full JSON. | ~17 MB |
| `ddi_knowledge_base.json` | The bulk-CSV backbone: 1,939 drugs and 160,235 pairs with severity only. Kept as the browsable, CSV-only subset for comparison (see finding 1 below). | ~50 MB |
| `ddi_mechanisms.json` | The enrichment layer on its own: 8,466 interaction groups, each with a real mechanism description, severity, and mechanism-category flags. This is where the clinical text lives. | ~3.5 MB |
| `enriched_sample.json` | 11 worked examples showing the complete record shape, mechanism text and all, for clinically important Major interactions. | ~14 KB |
| `interaction.schema.json` | JSON Schema (draft 2020-12) for a single interaction record. | ~2 KB |
| `ciel_ddinter_coverage_summary.json` | Aggregate result of the CIEL bridge: how many CIEL drug concepts have DDInter interaction data (see the CIEL section below). | ~1 KB |
| `ciel_rxnorm_crosswalk.json` | CIEL Drug concept (code + UUID + name) -> RxCUI(s), from the CIEL v2026-07-20 export. | ~1.2 MB |
| `ciel_ddinter_coverage.json` | Per-drug covered / gap lists behind the coverage summary. | ~1 MB |

`raw/` holds the eight source CSVs as downloaded. `enrich.py` / `build_enriched.py` regenerate the enriched KB; `rxnorm.py` does RxNorm normalization; `ciel_crosswalk.py` / `ciel_reconcile.py` / `ciel_coverage.py` build the CIEL bridge. The whole build is reproducible.

## The record shape

An interaction record looks like this:

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

Severity is one of `Major`, `Moderate`, `Minor`, `Unknown`. The `mechanism_categories` come straight from DDInter's own tagging: antagonistic effect, synergistic effect, absorption, distribution, metabolism, excretion, others.

## How the data is organized

DDInter 2.0 is built around roughly 8,466 interaction *groups*. Each group is one mechanism, written once, that then applies to many concrete drug pairs. So "potent CYP3A4 inhibitors raise sildenafil levels" is a single group that expands to sildenafil paired with each of a dozen-plus inhibitors. That's why the mechanism layer is small (~3.5 MB for all the clinical text) while the pair list is large.

The join is simple: every pair carries a `source_group_id`, and the group id resolves to its named pairs at `https://ddinter2.scbdd.com/server/inter-list/{group_id}/`. To enrich the full backbone rather than a sample, a maintainer walks all 8,466 group ids once and attaches each group's mechanism to its pairs. That fits the spec's "manual re-bundle on the release cycle" model exactly, and it's a batch job, not curation.

## Three things the data does differently from the spec

I want these visible, because they change what we can promise clinicians and ministries.

1. **The bulk CSV is only about half the data; the full ~302K is real but you have to walk the web API to get it.** The spec quotes DDInter 2.0's headline of about 302,000 interactions. The bulk CSV download holds only 160,235 unique pairs across 1,939 drugs. But when you walk DDInter's own group endpoint (all 8,466 groups, expanded to their named pairs), you get 302,515 pair rows, which dedupe to 295,184 unique pairs across 2,283 drugs. That lines up almost exactly with the paper's 302,516 interactions / 2,310 drugs. So the headline number is honest, the bulk CSV just isn't the whole database: it's missing ~135K pairs that only surface through the query interface. This matters for how we bundle. If the module ships the CSV, it silently covers about 53% of DDInter. If it ships the walked-and-enriched set (what `ddi_knowledge_base_enriched.json.gz` is), it covers the full database with mechanism text attached. Every one of the 160,235 CSV pairs is present in the enriched set, so nothing is lost by preferring it.

2. **The v1 and v2 bulk downloads are byte-identical.** I pulled from both `ddinter.scbdd.com` and `ddinter2.scbdd.com` and the eight files match to the byte. So "DDInter 2.0" as a *bulk download* is the same file set as v1. The 2.0 improvements appear to live in the web interface and its query endpoints, not in a richer bulk export.

3. **"Management recommendation" isn't really a field DDInter gives us.** The spec's FR 4.1 lists management guidance as part of the bundled content. In practice DDInter's text is a mechanism/effect description, and only about 8% of the 8,464 descriptions embed any management-style guidance, with only 15 using an explicit "Management" delimiter. So I've kept `management` in the schema as a nullable field and left it null rather than inventing guidance to fill it. That's the anti-hallucination principle from the spec's own "what must not happen" section, applied to our own build.

None of these is a reason to walk away from DDInter. It's still the best open, maintenance-free, offline-capable option we found, and the mechanism text is genuinely good. They're just things I'd want us to state plainly in the spec before the community reviews it.

For the record, here's what the enriched set actually contains: 295,184 unique pairs, of which 252,766 (about 85%) carry mechanism text; the rest are pairs DDInter lists without a written description. Severity breaks down as roughly 189K Moderate, 51K Major, 12K Minor, and 42K Unknown. Where the bulk CSV's per-pair severity and the group-level severity disagreed, I kept the CSV value as authoritative; that happened on 260 pairs out of 160,235, so about 0.16%.

## RxNorm normalization

This is done. Every drug now carries an `rxcui`, resolved from its name through the NLM RxNorm API (spec section 4.2). That's what lets "Panadol" and "acetaminophen" land on the same identifier so an interaction isn't missed on a naming difference, and it's the hook the CIEL bridge needs to map a patient's charted meds to these records.

All 2,283 drugs resolved: 2,151 (94%) by exact name match, 67 after stripping a dose-form qualifier like "(topical)", and 65 by a flagged approximate match. The approximate cases are almost all vaccines, biologics, and salts where DDInter's spelling differs slightly from RxNorm's, and each drug records how it was matched in `rxcui_match` so the lower-confidence ones can be reviewed rather than trusted blindly. The top-level `drugs[]` list also carries `rxnorm_name`, RxNorm's canonical name, for that audit.

One honest caveat: `rxcui` is the first concept id RxNorm returns for the name, which is normally the ingredient. I didn't force every match to ingredient-level term type, so a handful may point at a more specific concept. The `rxnorm_name` field makes those easy to spot if we want to tighten it later.

## The CIEL bridge

This is the link that makes the knowledge base usable from a real OpenMRS chart: a patient's medications are recorded as CIEL concepts, and CIEL maps those concepts to RxNorm, so CIEL concept -> RxCUI -> our interaction records. I pulled the full CIEL v2026-07-20 export from the Open Concept Lab and measured the overlap.

CIEL has 8,298 Drug-class concepts, of which 7,615 carry an RxNorm mapping. Matching those against DDInter, **4,738 (62.2%) have interaction data** in this knowledge base. That number needs a caveat that cuts the honest way: a naive exact-RxCUI match only found 23%, because CIEL's drug concepts are mostly products and formulations that map to product-level RxCUIs, while this KB stores ingredient-level RxCUIs. Reconciling both sides down to their RxNorm ingredient (via the RxNorm `related` API) is what gets you to the real 62%.

The remaining 2,877 CIEL drugs with no DDInter record are, overwhelmingly, things you would not expect a DDI database to carry: allergenic extracts, insect venoms, herbal and enzyme preparations, a few niche biologics. So the gap is mostly legitimate absence, not missing coverage. Either way, per the spec, the module surfaces these as a knowledge gap, never as a false "no interaction found."

The aggregate result lives in `out/ciel_ddinter_coverage_summary.json`, the full CIEL concept -> RxCUI crosswalk in `out/ciel_rxnorm_crosswalk.json`, and the per-drug covered/gap lists in `out/ciel_ddinter_coverage.json`. CIEL is an OpenMRS community terminology, included here with the permission of its maintainer and attributed in [ATTRIBUTION.md](ATTRIBUTION.md).

### Regenerating the CIEL crosswalk

The scripts pull CIEL from the Open Concept Lab. You need CIEL access (an OCL API token, which CIEL access is gated behind). Two ways in:

- **OCL CLI** (recommended for reproducibility): use the CLI to export the CIEL source, then run `ciel_crosswalk.py` against the exported `export.json`.
- **Direct export API**: `GET /orgs/CIEL/sources/CIEL/latest/export/` with an `Authorization: Token <token>` header returns a signed URL to the full source zip.

Then `ciel_crosswalk.py` builds the concept -> RxCUI crosswalk, `ciel_reconcile.py` does the ingredient-level match against the KB, and `ciel_coverage.py` writes the coverage report. No token or CIEL data is stored in this repo.

## What's still open

Community review of the findings before folding any of this into the spec, and confirmation of DDInter's redistribution terms now that the repo is public (CIEL is included with its maintainer's permission). Beyond that, the remaining work is module integration: taking a live patient medication list (CIEL concept UUIDs) and running it through concept -> RxCUI -> interaction lookup inside Chart Search AI, which is now a wiring exercise rather than a data problem.

## Provenance and license

Everything traces to DDInter 2.0 (https://ddinter2.scbdd.com/), an open-access database from the Computational Biology & Drug Design Group, peer-reviewed by pharmacists. Cite as: Xiong G, et al. DDInter 2.0: an enhanced drug interaction resource with expanded data coverage, new interaction types, and improved user interface. *Nucleic Acids Research.* 2025;53(D1):D1356-D1364.

The one authority caveat the spec already flags stands: DDInter is an academic database rather than a government-agency product. That's the single open concern on sourcing, and it's a governance conversation, not a data problem.

This repository is licensed under the **Mozilla Public License 2.0 with the OpenMRS Healthcare Disclaimer**, matching OpenMRS's own licensing. See [LICENSE](LICENSE), [HEALTHCARE_DISCLAIMER.md](HEALTHCARE_DISCLAIMER.md), and [ATTRIBUTION.md](ATTRIBUTION.md). The disclaimer matters here: this is decision support, the coverage is incomplete, and a missing pair is a knowledge gap, not a safety guarantee.
