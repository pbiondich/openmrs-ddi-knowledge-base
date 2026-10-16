"""Regressions for ingredient identity through the real offline build (issue #6)."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from query_kb import KB, Unresolved  # noqa: E402


class BuildKbTest(unittest.TestCase):
    # NLM RxNav ingredient identities; provenance is in docs/RXNORM-CORRECTIONS.md.
    CORRECTIONS = (
        ("DDInter1724", "10180", "sulfamethoxazole", "DB01015", "84471", "J01EC01", "Bactrim"),
        ("DDInter362", "2400", "chlorpheniramine", "DB01114", "913", "R06AB04", "Chlor-Trimeton"),
        ("DDInter1171", "6837", "methionine", "DB00134", "79692", "V03AB26", "Travasol 10"),
    )

    @staticmethod
    def prepare(root):
        shutil.copytree(ROOT / "src", root / "src")
        (root / "out").mkdir()

    @staticmethod
    def build(root):
        return subprocess.run(
            [sys.executable, str(ROOT / "build_kb.py")], cwd=root,
            capture_output=True, text=True,
        )

    @classmethod
    def setUpClass(cls):
        temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(temp.cleanup)
        root = Path(temp.name)
        cls.prepare(root)
        result = cls.build(root)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        cls.kb = KB.load(root / "out/ddi_knowledge_base.json")
        cls.ciel_index = json.loads((root / "out/ciel_index.json").read_text())["index"]

    def test_corrected_ingredient_identities_and_enrichment(self):
        for did, rx, name, drugbank, ciel, atc, brand in self.CORRECTIONS:
            with self.subTest(drug=did):
                drug = self.kb.resolve_one("id:" + did)
                self.assertEqual(drug["rxcui"], rx)
                self.assertEqual(drug["rxnorm_name"], name)
                self.assertEqual(drug["drugbank_id"], drugbank)
                self.assertEqual(drug["atc"], [atc])
                self.assertIn(brand, drug["brand_names"])
                self.assertIn(did, {d["id"] for d in self.kb.resolve("rxcui:" + rx)})
                self.assertIn(did, {d["id"] for d in self.kb.resolve(brand)})

    def test_corrected_ciel_bridges_reach_the_same_ingredient(self):
        for did, rx, name, drugbank, ciel, atc, brand in self.CORRECTIONS:
            with self.subTest(drug=did):
                drug = self.kb.resolve_one("id:" + did)
                concept = next((c for c in drug["ciel"] if c["code"] == ciel), None)
                self.assertIsNotNone(concept, f"{did} must bridge to CIEL {ciel}")
                self.assertIn(did, {d["id"] for d in self.kb.resolve("ciel:" + ciel)})
                self.assertIn(
                    {"ddinter_id": did, "rxcui": rx, "name": drug["name"]},
                    self.ciel_index[concept["uuid"]]["drugs"],
                )

    def test_unrelated_substances_no_longer_resolve_to_corrected_drugs(self):
        wrong_terms = (
            ("DDInter1724", "rxcui:10178"),
            ("DDInter1724", "ciel:105280"),
            ("DDInter1724", "ciel:84469"),
            ("DDInter362", "rxcui:1310122"),
            ("DDInter362", "ciel:162486"),
            ("DDInter1171", "rxcui:1426463"),
        )
        for did, term in wrong_terms:
            with self.subTest(drug=did, term=term):
                try:
                    matches = self.kb.resolve(term)
                except Unresolved:
                    matches = []
                self.assertNotIn(did, {d["id"] for d in matches})

    def test_combination_brands_and_ciel_keep_both_ingredients(self):
        for term in ("Bactrim", "Sulfatrim", "ciel:105281"):
            with self.subTest(term=term):
                self.assertEqual(
                    {d["name"] for d in self.kb.resolve(term)},
                    {"Sulfamethoxazole", "Trimethoprim"},
                )

    def test_missing_enrichment_cache_entries_fail_the_build(self):
        for filename in ("atc_cache.jsonl", "brand_names.jsonl"):
            with self.subTest(cache=filename), tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                self.prepare(root)
                path = root / "src" / filename
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertIn("10180", {r["rxcui"] for r in rows})
                path.write_text("".join(json.dumps(r) + "\n" for r in rows if r["rxcui"] != "10180"))
                result = self.build(root)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(filename, result.stdout + result.stderr)
                self.assertIn("10180", result.stdout + result.stderr)

    def test_explicit_empty_enrichment_cache_entries_are_valid(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            self.prepare(root)
            for filename, key in (("atc_cache.jsonl", "atc"), ("brand_names.jsonl", "brand_names")):
                path = root / "src" / filename
                rows = [json.loads(line) for line in path.read_text().splitlines()]
                self.assertIn("10180", {r["rxcui"] for r in rows})
                for row in rows:
                    if row["rxcui"] == "10180":
                        row[key] = []
                path.write_text("".join(json.dumps(r) + "\n" for r in rows))
            result = self.build(root)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            drug = KB.load(root / "out/ddi_knowledge_base.json").resolve_one("id:DDInter1724")
            self.assertEqual(drug["atc"], [])
            self.assertEqual(drug["brand_names"], [])


if __name__ == "__main__":
    unittest.main()
