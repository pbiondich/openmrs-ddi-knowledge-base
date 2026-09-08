"""
Exercises query_kb.py against the real built knowledge base (out/ddi_knowledge_base.json),
so it doubles as an integrity check on the build: every interaction row must join to a drug
and a mechanism, and the well-known clinical pairs must come back with the right severity.

Run: python3 -m unittest discover tests
"""
import json, os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from query_kb import KB, Unresolved, Ambiguous, SEVERITIES  # noqa: E402

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

    def test_search(self):
        names = [d["name"] for d in self.kb.search("statin")]
        self.assertIn("Simvastatin", names)
        self.assertEqual(names, sorted(names, key=str.lower))

    # --- command line ---
    def run_cli(self, *args):
        return subprocess.run([sys.executable, SCRIPT, *args], capture_output=True, text=True)

    def test_cli_json_pair(self):
        r = self.run_cli("--json", "pair", "warfarin", "aspirin")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)[0]["severity"], "Major")

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

    def test_cli_check_reports_gap_wording(self):
        r = self.run_cli("check", "warfarin", "notadrug")
        self.assertEqual(r.returncode, 0)
        self.assertIn("gap, not a clearance", r.stdout)
        self.assertIn("Not in the knowledge base: notadrug", r.stdout)


if __name__ == "__main__":
    unittest.main()
