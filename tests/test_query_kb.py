"""
Exercises query_kb.py against the real built knowledge base (out/ddi_knowledge_base.json),
so it doubles as an integrity check on the build: every interaction row must join to a drug
and a mechanism, and the well-known clinical pairs must come back with the right severity.

Run: python3 -m unittest discover tests
"""
import json, os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from query_kb import KB, Unresolved, Ambiguous, SEVERITIES, condition_terms  # noqa: E402

SCRIPT = os.path.join(ROOT, "query_kb.py")


class QueryKbTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.kb = KB.load()

    # --- integrity of the built KB ---
    def test_every_interaction_row_joins(self):
        kb = self.kb
        for (a, b), (sev, gid) in kb.rows.items():
            self.assertIn(a, kb.by_id); self.assertIn(b, kb.by_id)
            self.assertIn(sev, SEVERITIES)
            self.assertIn(gid, kb.mechanisms)

    def test_sentinel_mechanism(self):
        self.assertIsNone(self.kb.mechanism("-1")["text"])
        self.assertIsNone(self.kb.mechanism("no-such-group"))

    def test_atc_codes_are_level_5(self):
        bad = [c for d in self.kb.drugs for c in d["atc"] if len(c) != 7]
        self.assertEqual(bad, [])

    # --- resolution ---
    def test_resolve_by_every_kind_of_term(self):
        for term in ("warfarin", "Warfarin", "rxcui:11289", "ciel:86415", "drugbank:DB00682",
                     "id:DDInter1951", "DDInter1951", "Warfarin sodium"):
            self.assertEqual(self.kb.resolve_one(term)["name"], "Warfarin", term)
        self.assertEqual(self.kb.resolve_one("aspirin")["name"], "Acetylsalicylic acid")  # RxNorm name

    def test_unresolved_offers_suggestions(self):
        with self.assertRaises(Unresolved) as cm:
            self.kb.resolve("warfarine")
        self.assertIn("warfarin", cm.exception.suggestions)
        with self.assertRaises(Unresolved):
            self.kb.resolve("rxcui:0")
        with self.assertRaises(ValueError):
            self.kb.resolve("snomed:123")

    def test_combination_ciel_name_is_ambiguous(self):
        found = self.kb.resolve("Acetaminophen / aspirin")
        self.assertEqual(sorted(d["name"] for d in found), ["Acetaminophen", "Acetylsalicylic acid"])
        with self.assertRaises(Ambiguous):
            self.kb.resolve_one("Acetaminophen / aspirin")

    # --- questions ---
    def test_pair_warfarin_aspirin_is_major_and_symmetric(self):
        ab = self.kb.pair("warfarin", "aspirin")
        ba = self.kb.pair("aspirin", "warfarin")
        self.assertEqual(len(ab), 1)
        self.assertEqual(ab[0]["severity"], "Major")
        self.assertIn("bleeding", ab[0]["mechanism"].lower())
        self.assertEqual(ab[0]["severity"], ba[0]["severity"])
        self.assertEqual(ab[0]["group_id"], ba[0]["group_id"])

    def test_pair_not_on_file_is_empty_not_error(self):
        kb = self.kb
        w = kb.resolve_one("warfarin")
        others = [d for d in kb.drugs if d["id"] != w["id"]
                  and (min(w["id"], d["id"]), max(w["id"], d["id"])) not in kb.rows]
        self.assertTrue(others, "warfarin should not interact with every drug")
        self.assertEqual(kb.pair("warfarin", others[0]["name"]), [])

    def test_check_medication_list(self):
        res = self.kb.check(["warfarin", "aspirin", "simvastatin", "clarithromycin", "notadrug"])
        pairs = {frozenset((r["drug_a"]["name"], r["drug_b"]["name"])): r["severity"] for r in res["interactions"]}
        self.assertEqual(pairs[frozenset(("Warfarin", "Acetylsalicylic acid"))], "Major")
        self.assertEqual(pairs[frozenset(("Simvastatin", "Clarithromycin"))], "Major")
        ranks = [SEVERITIES.index(r["severity"]) for r in res["interactions"]]
        self.assertEqual(ranks, sorted(ranks), "most severe first")
        self.assertEqual([u["term"] for u in res["unresolved"]], ["notadrug"])
        self.assertEqual(len(res["checked"]), 4)

    def test_partners_filter_matches_profile_counts(self):
        prof = self.kb.profile("warfarin")[0]
        major = self.kb.partners("warfarin", ["Major"])
        self.assertTrue(all(r["severity"] == "Major" for r in major))
        self.assertEqual(len(major), prof["partner_counts"]["Major"])
        self.assertEqual(len(self.kb.partners("warfarin")), prof["partners_total"])
        self.assertIn("Acetylsalicylic acid", [r["partner"]["name"] for r in major])

    def test_coverage_includes_groups_missing_from_bulk_downloads(self):
        cov = self.kb.coverage()
        by = {g["atc"]: g for g in cov["groups"]}
        self.assertEqual(sorted(by), sorted("ABCDGHJLMNPRSV"))
        for letter in "CGJMNS":                       # absent from DDInter's downloads, present here
            self.assertFalse(by[letter]["in_bulk_downloads"])
            self.assertGreater(by[letter]["drugs"], 50, letter)
            self.assertGreater(by[letter]["interaction_rows"], 10000, letter)
        self.assertGreater(cov["drugs_without_atc"], 0)
        r = self.run_cli("coverage")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("| N | Nervous system |", r.stdout)

    def test_search(self):
        names = [d["name"] for d in self.kb.search("statin")]
        self.assertIn("Simvastatin", names)
        self.assertEqual(names, sorted(names, key=str.lower))

    # --- drug-disease table and derived findings ---
    def test_every_disease_row_joins(self):
        kb = self.kb
        self.assertTrue(kb.conditions_of, "the drug-disease table should be present")
        for did, rows in kb.conditions_of.items():
            self.assertIn(did, kb.by_id)
            for condition, sev, nid in rows:
                self.assertTrue(condition)
                self.assertIn(sev, SEVERITIES)
                self.assertIn(nid, kb.disease_notes)

    def test_metformin_lactic_acidosis_is_major_with_references(self):
        rows = {r["condition"]: r for r in self.kb.conditions("metformin")}
        row = rows["Acidosis, Lactic"]
        self.assertEqual(row["severity"], "Major")
        self.assertIn("lactic acidosis", row["text"].lower())
        self.assertTrue(row["references"])
        sevs = [SEVERITIES.index(r["severity"]) for r in self.kb.conditions("metformin")]
        self.assertEqual(sevs, sorted(sevs), "most severe first")

    def test_stavudine_metformin_is_unknown_pairwise_but_derived_via_lactic_acidosis(self):
        pair = self.kb.pair("stavudine", "metformin")
        self.assertEqual([r["severity"] for r in pair], ["Unknown"])   # DDInter's pairwise row
        derived = self.kb.derived("stavudine", "metformin")
        hit = [r for r in derived if r["condition"] == "Acidosis, Lactic"]
        self.assertTrue(hit, derived)
        self.assertIn("Stavudine", hit[0]["basis"])                  # stavudine's text names it
        self.assertEqual(hit[0]["b"]["severity"], "Major")          # metformin's rating
        # symmetric: the same conditions come back whichever way the pair is asked
        self.assertEqual({r["condition"] for r in derived},
                         {r["condition"] for r in self.kb.derived("metformin", "stavudine")})

    def test_check_carries_derived_findings(self):
        res = self.kb.check(["stavudine", "metformin"])
        self.assertIn("Acidosis, Lactic", [r["condition"] for r in res["derived"]])

    def test_condition_terms(self):
        self.assertIn("lactic acidosis", condition_terms("Acidosis, Lactic"))
        self.assertIn("liver disease", condition_terms("Liver Diseases"))

    # --- command line ---
    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)

    def test_cli_json_pair(self):
        r = self.run_cli("--json", "pair", "warfarin", "aspirin")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["interactions"][0]["severity"], "Major")
        self.assertEqual(out["derived"], [], "warfarin/aspirin share precautions but form no causal chain")

    def test_cli_gap_and_errors(self):
        r = self.run_cli("pair", "warfarin", "warfarine")
        self.assertEqual(r.returncode, 2)
        self.assertIn("Did you mean", r.stderr)
        r = self.run_cli("pair", "warfarin", "Acetaminophen / aspirin")
        self.assertEqual(r.returncode, 0, r.stderr)   # shared-name terms fan out, they do not fail
        self.assertIn("Major", r.stdout)
        r = self.run_cli("drug", "Acetaminophen / aspirin")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(r.stdout.count("RxCUI"), 2)

    def test_cli_pair_and_conditions_show_derived(self):
        r = self.run_cli("pair", "stavudine", "metformin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("Unknown", r.stdout)
        self.assertIn("Derived (condition-mediated", r.stdout)
        self.assertIn("Acidosis, Lactic", r.stdout)
        r = self.run_cli("--json", "pair", "stavudine", "metformin")
        out = json.loads(r.stdout)
        self.assertEqual(out["interactions"][0]["severity"], "Unknown")
        self.assertTrue(out["derived"])
        r = self.run_cli("conditions", "metformin")
        self.assertIn("Acidosis, Lactic", r.stdout)

    def test_cli_check_reports_gap_wording(self):
        r = self.run_cli("check", "warfarin", "notadrug")
        self.assertEqual(r.returncode, 0)
        self.assertIn("gap, not a clearance", r.stdout)
        self.assertIn("Not in the knowledge base: notadrug", r.stdout)


if __name__ == "__main__":
    unittest.main()
