# Proposal: consume the knowledge base's drug-disease rows and its derived tier (schema 1.2)

Posted to the module repository as
[openmrs/openmrs-module-chartsearchai#391](https://github.com/openmrs/openmrs-module-chartsearchai/issues/391)
on 2026-09-08. This copy is the text as posted.

The `ddinter` source ships the whole knowledge base byte-identical to a release of
[openmrs-ddi-knowledge-base](https://github.com/pbiondich/openmrs-ddi-knowledge-base) (ADR Decision 36).
That knowledge base has grown two tables since the copy the module bundles (schema 1.0, July). This
proposes that the module read them. It is two changes of different size, and I would be happy for them
to be split into separate issues if that is easier to review.

## The case that motivated it

A patient on stavudine is asked about metformin. DDInter's drug-drug row for that pair is `Unknown`
with no text, so the rule arm has nothing to raise and the default severity floor (`minor`) filters
it anyway. The clinician sees no chip. Yet DDInter carries both halves of the concern in its
drug-disease table:

- stavudine, `Liver Diseases`, Major: "Hepatotoxicity including **lactic acidosis**, severe hepatomegaly
  with steatosis ... has been associated with the use of some nucleoside reverse transcriptase inhibitors"
- metformin, `Acidosis, Lactic`, Major: "The use of metformin is contraindicated in patients with ... any
  condition associated with hypoxemia" (seven references, from Luft 1978 to Wiholm 1993)

DDInter never joins its two tables, so the pair reads as unrated. The knowledge base now carries the
drug-disease rows and, on top of them, a derived tier that records exactly that chain.

## What changed in the knowledge base

Two tables were added, both built reproducibly by `build_kb.py` from committed inputs.

| Table | Rows | What a row is |
|---|---|---|
| `disease_interactions` | 8,346 across 1,480 drugs and 470 conditions | `[drug_id, condition, severity, note_id]`: DDInter's drug-disease rating, with the description and references interned once in `disease_notes` (3,942) |
| `derived_interactions` | 111,138 linking 97,493 pairs through 185 conditions | `[cause_drug, cause_condition, cause_severity, cause_note, rated_drug, condition, rated_severity, rated_note]`: a causal chain, one drug's text says it causes a condition the other drug is rated for |

The derived tier is an inference, and the knowledge base says so in its metadata, its schema, and its
README. A row exists only when a sentence in the cause drug's drug-disease text names the condition on a
word boundary, carries a causal cue ("may cause", "associated with", "induce", "worsen", "have been
reported with"), and carries no precaution phrasing ("in patients with", "history of"). Two drugs
merely sharing a precaution is deliberately not a chain; 667 drugs carry a `Kidney Diseases` row, and
linking on that would fire on most pairs. The matcher is a text heuristic and the README says what that
means: it will miss chains phrased in ways it does not recognize, and it will occasionally link through
a mention that reads as causal but is not. Both source rows are cited by note id on every derived row,
so a reader can check the chain.

Against DDInter's own pairwise rows, the 97,493 derived pairs break down as: 65,406 that DDInter does
not list at all, 5,021 it rates `Unknown`, and 27,066 it already rates. So for roughly 70,000 pairs the
derived tier is the only thing the knowledge base has to say.

Reproduce any of this from the knowledge base repository:

```
python3 query_kb.py pair stavudine metformin      # the Unknown row, then the lactic-acidosis chain
python3 query_kb.py conditions metformin          # a drug's drug-disease rows
python3 query_kb.py check stavudine metformin lamivudine
```

## Compatibility: the new file is a drop-in

`DdiDrugReferenceSource` reads the JSON by key (`root.get("drugs")`, `root.path("mechanisms")`,
`root.get("interactions")`), so a schema 1.2 file parses today and the new tables are ignored until
code reads them. What does change on a refresh is size: the file grows from 18.9 MB to 34.7 MB, so the
packed jar grows by a few MB and the cold parse takes somewhat longer. Retained memory is unchanged
until the new tables are read. The hash-provenance story in ADR Decision 36 is unaffected.

## Part A: drug-disease rows as condition rules

This is the smaller change and, I think, the one to do first. Today the shipped default pins
`Arm.CONDITION_RULES` as `ABSENT` (`ShippedDrugReferenceDefaultTest`), and the scope note in
`DdiDrugReferenceSource` says entries never expose `contraindications`. Issues #285 and #378 both turn
on that gap: no default install can raise a condition contraindication, and a screen that cannot ask
about conditions is indistinguishable on the wire from one that asked and found nothing.

The drug-disease rows fill that gap with DDInter's own data rather than hand-authored rules. The
source would expose each row as a `Contraindication` of `type: "condition"`:

- The token should be the condition name in natural word order, `lactic acidosis` rather than DDInter's
  MeSH-style `Acidosis, Lactic`, because `PatientClinicalContext` matches condition tokens by
  containment against the chart's lowercased condition text (issue #309). The knowledge base
  repository's adapter (`adapt_to_chartsearchai.py`) already does this transformation for the `json`
  format, so the rule is written down and testable.
- The note should carry the severity and the description, in the form the interaction notes already
  use: `Major. The use of metformin is contraindicated in patients with ...`.
- Containment matching on a condition name has the same limits it has for allergies: `liver diseases`
  will not match a chart that records `cirrhosis`. That is a matching question, not a data one, and I
  would rather ship the rows and improve matching than hold the rows for it.

This flips a pinned assertion deliberately, so it is a spec change for `ShippedDrugReferenceDefaultTest`
and for the scope prose in `config.xml`, the README, and the source javadoc.

## Part B: the derived tier as its own warning class

This is the new capability. The derived rows should reach the clinician as a warning type of their
own, distinct from `interaction`, so they can never be confused with, folded into, or ranked against a
DDInter pairwise rating. A working name is `condition-mediated`.

**When it fires.** The same shape as the interaction arm: one drug is in play (the question drug or an
active order) and the other is an active order, and the knowledge base has a derived row in either
direction between the two substances. One chip per pair and condition. The same substance-identity
handling the interaction arm uses (#130) applies, so route variants of one substance do not produce
several chips.

**What it says.** Both halves and the reason, with both source rows citable:

> Stavudine can cause lactic acidosis (DDInter drug-disease, Major). Metformin is contraindicated in
> lactic acidosis (Major). Derived from DDInter's drug-disease rows; not a DDInter pairwise rating.

**How much of it to show.** All 97,493 pairs is too many to surface by default; the common linking
conditions are hypotension, heart failure, and seizures, which are real but often additive-effect
class chains. The rated side's severity is the natural gate. Restricting to chains whose rated drug is
`Major` for the condition gives 40,764 pairs, of which 28,800 are silent today (DDInter row `Unknown`
or absent). Requiring both sides `Major` gives 24,804 pairs, 17,463 silent today. I would suggest a
global property alongside `minInteractionSeverity`, say `chartsearchai.drugSafety.derivedFindings`
with values `off`, `major`, and `all`, defaulting to `major`, and I would defer to whoever measures it
on the standalone.

**What it does not do.** It never assigns the pair a severity of its own, never changes a DDInter
pairwise row, and never fills the `Unknown` row's empty mechanism. When the chart already records the
condition, Part A's contraindication chip for the rated drug fires on its own; whether the derived
chip should then stand down or fold is a design question I would leave to the implementer.

## What I am not proposing

- Assigning severities to DDInter's `Unknown` pairs, or any clinician overlay on DDInter's ratings.
- The drug-food table. DDInter publishes one (metformin and alcohol, for example, and it carries the
  only management text DDInter has), and the knowledge base does not ingest it yet.

## Verification I would expect

In the style this repository already holds itself to: tests through the real validator and injector
against the shipped knowledge base, with the stavudine and metformin case as the specification for
Part B and the shipped-default test updated deliberately for Part A; and a before-and-after capture on
the standalone, the way #130 was verified, with a patient on stavudine asked about metformin producing
no chip before and one labelled derived chip after.

## References

- Knowledge base commits: `783df57` (drug-disease table), `30df3c9` (matcher: whole-word, causal
  sentence), `aeb912a` (derived tier materialized, schema 1.2).
- Knowledge base README, sections "The record shape", "Asking it questions", and "What it is not".
- Module issues this touches: #285, #378 (condition rules absent by default), #309 (containment
  matching), #108 (severity floor), #130 (substance-identity fold), #84 (the original ddinter proposal).
