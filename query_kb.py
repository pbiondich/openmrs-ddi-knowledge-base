"""
query_kb.py — ask the knowledge base a question from the command line.

Loads out/ddi_knowledge_base.json and does the three-table joins, so a question
takes one line instead of a script:

  python3 query_kb.py pair warfarin aspirin                do these two interact? severity + mechanism
  python3 query_kb.py check warfarin aspirin simvastatin   every interacting pair in a medication list
  python3 query_kb.py partners warfarin --severity Major   a drug's interacting partners, most severe first
  python3 query_kb.py drug warfarin                        identifiers, ATC, CIEL concepts, partner counts
  python3 query_kb.py conditions metformin                 a drug's disease interactions (DDInter drug-disease table)
  python3 query_kb.py mechanism 34                         a mechanism group's text and categories
  python3 query_kb.py search statin                        drugs whose name contains a string
  python3 query_kb.py coverage                             drugs and interaction rows per ATC group

Name a drug by its DDInter name, RxNorm name, RxNorm brand name (panadol, zocor), or CIEL
concept name (case-insensitive), or by identifier with a prefix: rxcui:11289, ciel:86415,
drugbank:DB00682, id:DDInter1951.
--json on any command prints machine-readable output; --kb PATH points at another file.

pair and check also report DERIVED findings: a causal chain through the drug-disease table,
where one drug's rating text names a condition the other drug is rated for (stavudine's
"Liver Diseases" text names lactic acidosis; metformin is rated Major for "Acidosis,
Lactic"). Those are inferences, labelled as such, not DDInter pairwise ratings.

Importable: from query_kb import KB; kb = KB.load(); kb.pair("warfarin", "aspirin").
A pair with no record is a knowledge gap, never a clearance (see README).
"""
import argparse, difflib, functools, json, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KB = os.path.join(HERE, "out", "ddi_knowledge_base.json")
SEVERITIES = ["Major", "Moderate", "Minor", "Unknown"]
RANK = {s: i for i, s in enumerate(SEVERITIES)}
PREFIXES = ("rxcui", "ciel", "drugbank", "id")
ATC_GROUPS = {"A": "Alimentary tract and metabolism", "B": "Blood and blood forming organs",
              "C": "Cardiovascular system", "D": "Dermatologicals",
              "G": "Genito-urinary system and sex hormones", "H": "Systemic hormonal preparations",
              "J": "Anti-infectives for systemic use", "L": "Antineoplastic and immunomodulating agents",
              "M": "Musculo-skeletal system", "N": "Nervous system", "P": "Antiparasitic products",
              "R": "Respiratory system", "S": "Sensory organs", "V": "Various"}
BULK_DOWNLOAD_GROUPS = set("ABDHLPRV")     # the only groups DDInter's download page offers, as of 2026-09


class Unresolved(LookupError):
    """A drug term matched nothing; .suggestions holds close names to try."""
    def __init__(self, term, suggestions):
        super().__init__(f"no drug matches {term!r}")
        self.term, self.suggestions = term, suggestions


class Ambiguous(LookupError):
    """A drug term matched several drugs; .drugs holds them (pick one by id:)."""
    def __init__(self, term, drugs):
        super().__init__(f"{term!r} matches {len(drugs)} drugs")
        self.term, self.drugs = term, drugs


def brief(d):
    return {"id": d["id"], "name": d["name"], "rxcui": d["rxcui"]}


@functools.lru_cache(maxsize=None)
def condition_terms(name):
    """The forms a MeSH-style condition name takes in prose: "Acidosis, Lactic" -> "lactic acidosis",
    plus the singular of a plural head noun ("Liver Diseases" -> "liver disease")."""
    low = name.lower().strip()
    forms = {low, " ".join(reversed([p.strip() for p in low.split(",")]))}
    forms |= {f[:-1] for f in forms if f.endswith("s")}
    return frozenset(forms)


# A sentence establishes a causal chain only when it says the drug CAUSES or WORSENS the condition.
# "Use with caution in patients with hypertension" names hypertension but is a precaution about
# patients who already have it, which is the shared-precaution noise this deliberately excludes.
# Measured on the full KB: dropping the causal test triples the derived pairs, and the extra ones are
# dominated by exactly that phrasing.
CAUSAL = re.compile(r"\b(cause[sd]?|causing|induce[sd]?|inducing|associated with|risk of|result(?:s|ed)? in"
                    r"|precipitat\w+|exacerbat\w+|worsen\w*|aggravat\w+|produce[sd]?|lead(?:s|ing)? to"
                    r"|develop(?:ment)? of|(?:been|were|was) reported)\b")   # "have been reported with", not "in reported cases"
PRECAUTION = re.compile(r"\b(patients? with|history of|pre-?existing|underlying|susceptible"
                        r"|caution(?:ed|ary|sly)? in|contraindicated in|compromised|impair(?:ed|ment))\b")
_SENTENCES = re.compile(r"(?<=[.;])\s+")


@functools.lru_cache(maxsize=None)
def _condition_pattern(name):
    terms = sorted(condition_terms(name), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(t) for t in terms) + r")\b")   # whole words: "tics" is not in "antibiotics"


@functools.lru_cache(maxsize=None)
def causal_sentences(text):
    """The sentences of a drug-disease text that assert causation and are not precautions. Cached
    because build_kb.py asks this of every note for every condition."""
    return tuple(s for s in _SENTENCES.split((text or "").lower()) if CAUSAL.search(s) and not PRECAUTION.search(s))


def names_as_caused(text, condition):
    """True when some sentence of a drug-disease text says the drug causes or worsens the condition."""
    pat = _condition_pattern(condition)
    return any(pat.search(s) for s in causal_sentences(text))


def condition_links(ra, rb):
    """The causal chains two drug-disease rows form, as (condition, cause_side, basis) with cause_side
    "a" or "b": one row's text says its drug causes the OTHER row's condition (stavudine's "Liver
    Diseases" text: hepatotoxicity including lactic acidosis is associated with NRTIs; metformin is
    rated Major for "Acidosis, Lactic"). Both directions can hold at once, so this returns a list.
    Two rows about the same condition are deliberately not a link: 667 drugs carry a "Kidney
    Diseases" row, so "both rated for it" would fire on most pairs and says only that each drug needs
    care in that condition, which `conditions` already reports per drug."""
    if condition_terms(ra["condition"]) & condition_terms(rb["condition"]):
        return []
    out = []
    if names_as_caused(ra["text"], rb["condition"]):
        out.append((rb["condition"], "a", f"{ra['drug']['name']}'s \"{ra['condition']}\" text says it causes this condition"))
    if names_as_caused(rb["text"], ra["condition"]):
        out.append((ra["condition"], "b", f"{rb['drug']['name']}'s \"{rb['condition']}\" text says it causes this condition"))
    return out


class KB:
    def __init__(self, data):
        self.meta = data["metadata"]
        self.mechanisms = data["mechanisms"]
        self.drugs = data["drugs"]
        self.by_id = {d["id"]: d for d in self.drugs}
        # --- identifier indexes (rxcui and ciel are one-to-many by design) ---
        self.by_rxcui, self.by_ciel, self.by_drugbank = {}, {}, {}
        for d in self.drugs:
            if d["rxcui"]:
                self.by_rxcui.setdefault(d["rxcui"], []).append(d)
            if d["drugbank_id"]:
                self.by_drugbank.setdefault(d["drugbank_id"].upper(), []).append(d)
            for c in d["ciel"]:
                self.by_ciel.setdefault(c["code"], []).append(d)
        # --- name indexes, in precedence order: DDInter name, RxNorm name, brand name, CIEL concept name ---
        self.by_name, self.by_rxname, self.by_brand, self.by_cielname = {}, {}, {}, {}
        for d in self.drugs:
            self.by_name.setdefault(d["name"].lower(), []).append(d)
            if d["rxnorm_name"]:
                self.by_rxname.setdefault(d["rxnorm_name"].lower(), []).append(d)
            for b in d.get("brand_names", []):
                self.by_brand.setdefault(b.lower(), []).append(d)
            for c in d["ciel"]:
                if c["name"]:
                    self.by_cielname.setdefault(c["name"].lower(), []).append(d)
        self.all_names = sorted(set(self.by_name) | set(self.by_rxname) | set(self.by_brand))
        # --- interaction indexes: one row per unordered pair; partners per drug ---
        self.rows, self.partners_of = {}, {}
        for a, b, sev, gid in data["interactions"]:
            self.rows[(a, b) if a <= b else (b, a)] = (sev, gid)
            self.partners_of.setdefault(a, []).append((b, sev, gid))
            if a != b:
                self.partners_of.setdefault(b, []).append((a, sev, gid))
        # --- drug-disease rows per drug (.get: a KB built before this table existed still loads) ---
        self.disease_notes = data.get("disease_notes", {})
        self.conditions_of = {}
        for did, condition, sev, nid in data.get("disease_interactions", []):
            self.conditions_of.setdefault(did, []).append((condition, sev, nid))
        # --- derived tier as materialized by build_kb.py (same matcher); None on a KB without it ---
        self.derived_rows = data.get("derived_interactions")
        self.derived_of = {}
        for cause, ccond, csev, cnote, rated, cond, rsev, rnote in self.derived_rows or []:
            self.derived_of.setdefault((cause, rated), []).append((ccond, csev, cnote, cond, rsev, rnote))

    @classmethod
    def load(cls, path=DEFAULT_KB):
        with open(path) as f:
            return cls(json.load(f))

    # --- resolution ---
    def resolve(self, term):
        """All drugs a term names. Identifier prefixes are exact; a bare name tries the DDInter
        name, then the RxNorm name, then RxNorm brand names, then CIEL concept names. Raises
        Unresolved when nothing matches."""
        t = term.strip()
        if ":" in t:
            kind, _, val = t.partition(":")
            kind, val = kind.lower(), val.strip()
            if kind not in PREFIXES:
                raise ValueError(f"unknown identifier prefix {kind!r}; use one of " + ", ".join(p + ":" for p in PREFIXES))
            found = {"rxcui": self.by_rxcui.get(val), "ciel": self.by_ciel.get(val),
                     "drugbank": self.by_drugbank.get(val.upper()),
                     "id": [self.by_id[val]] if val in self.by_id else None}[kind]
            if not found:
                raise Unresolved(t, [])
            return list(found)
        if t in self.by_id:
            return [self.by_id[t]]
        low = t.lower()
        for index in (self.by_name, self.by_rxname, self.by_brand, self.by_cielname):
            if low in index:
                return list(index[low])
        raise Unresolved(t, difflib.get_close_matches(low, self.all_names, n=5, cutoff=0.6))

    def resolve_one(self, term):
        """Exactly one drug, or Ambiguous listing the candidates."""
        found = self.resolve(term)
        if len(found) > 1:
            raise Ambiguous(term, found)
        return found[0]

    # --- questions ---
    def mechanism(self, gid):
        m = self.mechanisms.get(str(gid))
        return None if m is None else {"group_id": str(gid), "text": m["text"], "categories": m["categories"]}

    def interaction(self, a, b):
        """The record for two drug dicts, or None when the KB holds no row for the pair."""
        key = (a["id"], b["id"]) if a["id"] <= b["id"] else (b["id"], a["id"])
        hit = self.rows.get(key)
        if hit is None:
            return None
        sev, gid = hit
        m = self.mechanisms.get(gid, {})
        return {"drug_a": brief(a), "drug_b": brief(b), "severity": sev, "group_id": gid,
                "mechanism": m.get("text"), "categories": m.get("categories", [])}

    def pair(self, term_a, term_b):
        """Every record among the drugs the two terms resolve to (one in the usual case; more
        when an identifier is shared). An empty list means the pair is not on file."""
        out = []
        for a in self.resolve(term_a):
            for b in self.resolve(term_b):
                rec = self.interaction(a, b)
                if rec:
                    out.append(rec)
        return out

    def _conditions_for(self, d):
        out = []
        for condition, sev, nid in self.conditions_of.get(d["id"], []):
            n = self.disease_notes.get(nid, {})
            out.append({"drug": brief(d), "condition": condition, "severity": sev,
                        "text": n.get("text"), "references": n.get("references", [])})
        out.sort(key=lambda r: (RANK[r["severity"]], r["condition"]))
        return out

    def conditions(self, term):
        """A drug's disease interactions from DDInter's drug-disease table, most severe first."""
        out = []
        for d in self.resolve(term):
            out.extend(self._conditions_for(d))
        return out

    def _derived_for(self, a, b):
        """Derived chains between two drug dicts: from the KB's materialized table when it has one,
        else computed with the same matcher (a KB built before the table existed)."""
        if self.derived_rows is None:
            return self._derived_compute(a, b)
        out = []
        for cause, rated in ((a, b), (b, a)):
            for ccond, csev, cnote, cond, rsev, rnote in self.derived_of.get((cause["id"], rated["id"]), []):
                cause_side = {"condition": ccond, "severity": csev, "text": self.disease_notes[cnote]["text"]}
                rated_side = {"condition": cond, "severity": rsev, "text": self.disease_notes[rnote]["text"]}
                out.append({"drug_a": brief(a), "drug_b": brief(b), "condition": cond,
                            "basis": f"{cause['name']}'s \"{ccond}\" text says it causes this condition",
                            "a": cause_side if cause is a else rated_side,
                            "b": rated_side if cause is a else cause_side})
        return out

    def _derived_compute(self, a, b):
        out, seen = [], set()
        for ra in self._conditions_for(a):          # most severe first, so the first hit per chain wins
            for rb in self._conditions_for(b):
                for condition, cause_side, basis in condition_links(ra, rb):
                    # One chain per (cause drug, rated drug, condition), as build_kb.py materializes it: the
                    # most severe rows win because _conditions_for yields most severe first.
                    key = (condition, cause_side)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"drug_a": brief(a), "drug_b": brief(b), "condition": condition, "basis": basis,
                                "a": {k: ra[k] for k in ("condition", "severity", "text")},
                                "b": {k: rb[k] for k in ("condition", "severity", "text")}})
        return out

    def derived(self, term_a, term_b):
        """Condition-mediated findings for two drugs, derived from the drug-disease table rather than
        read from a DDInter pairwise row: one drug's rating text names a condition the other drug is
        rated for (a causal chain). Inferences, labelled as such wherever shown."""
        out = []
        for a in self.resolve(term_a):
            for b in self.resolve(term_b):
                if a["id"] != b["id"]:
                    out.extend(self._derived_for(a, b))
        out.sort(key=lambda r: (min(RANK[r["a"]["severity"]], RANK[r["b"]["severity"]]), r["condition"]))
        return out

    def check(self, terms):
        """Every interacting pair among a medication list, most severe first, plus derived
        condition-mediated findings, plus the terms that could not be resolved, so a gap is
        reported rather than swallowed."""
        resolved, unresolved = [], []
        for t in terms:
            try:
                resolved.extend(self.resolve(t))
            except Unresolved as e:
                unresolved.append({"term": t, "suggestions": e.suggestions})
        found, derived = [], []
        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                a, b = resolved[i], resolved[j]
                if a["id"] == b["id"]:
                    continue
                rec = self.interaction(a, b)
                if rec:
                    found.append(rec)
                derived.extend(self._derived_for(a, b))
        found.sort(key=lambda r: (RANK[r["severity"]], r["drug_a"]["name"], r["drug_b"]["name"]))
        derived.sort(key=lambda r: (min(RANK[r["a"]["severity"]], RANK[r["b"]["severity"]]), r["condition"]))
        return {"checked": [brief(d) for d in resolved], "interactions": found, "derived": derived,
                "unresolved": unresolved}

    def partners(self, term, severities=None):
        """A drug's interacting partners, most severe first and then by name."""
        out = []
        for d in self.resolve(term):
            for pid, sev, gid in self.partners_of.get(d["id"], []):
                if severities and sev not in severities:
                    continue
                m = self.mechanisms.get(gid, {})
                out.append({"drug": brief(d), "partner": brief(self.by_id[pid]), "severity": sev,
                            "group_id": gid, "mechanism": m.get("text")})
        out.sort(key=lambda r: (RANK[r["severity"]], r["partner"]["name"]))
        return out

    def profile(self, term):
        """A drug's identifiers plus how many partners it has at each severity."""
        out = []
        for d in self.resolve(term):
            counts = {s: 0 for s in SEVERITIES}
            for _, sev, _ in self.partners_of.get(d["id"], []):
                counts[sev] += 1
            conds = {s: 0 for s in SEVERITIES}
            for _, sev, _ in self.conditions_of.get(d["id"], []):
                conds[sev] += 1
            out.append(dict(d, partner_counts=counts, partners_total=sum(counts.values()),
                            condition_counts=conds, conditions_total=sum(conds.values())))
        return out

    def coverage(self):
        """Drugs and interaction rows per ATC first-level (anatomical) group, plus the drugs carrying
        no ATC code. A row counts toward every group either drug belongs to, so rows sum to more than
        the KB total. Exists to show at a glance that the groups DDInter's bulk downloads omit are
        covered: the downloads carry only A, B, D, H, L, P, R, and V."""
        groups = {}
        for d in self.drugs:
            for c in d["atc"]:
                groups.setdefault(c[0], set()).add(d["id"])
        out = []
        for letter in sorted(ATC_GROUPS):
            ds = groups.get(letter, set())
            rows = sum(1 for a, b in self.rows if a in ds or b in ds)
            out.append({"atc": letter, "group": ATC_GROUPS[letter], "drugs": len(ds), "interaction_rows": rows,
                        "in_bulk_downloads": letter in BULK_DOWNLOAD_GROUPS})
        return {"groups": out, "drugs_without_atc": sum(1 for d in self.drugs if not d["atc"])}

    def search(self, text):
        """Drugs whose DDInter, RxNorm, brand, or CIEL name contains the text. A hit found only through
        a brand or a CIEL combination name (say "Imipenem / cilastatin" for "statin") carries that name
        in matched_via, so the reader can see why an unexpected drug is in the list."""
        low = text.lower()
        hits = []
        for d in self.drugs:
            if low in d["name"].lower() or (d["rxnorm_name"] and low in d["rxnorm_name"].lower()):
                hits.append(dict(d, matched_via=None))
                continue
            via = [f'brand "{b}"' for b in d.get("brand_names", []) if low in b.lower()]
            via += [f'CIEL "{c["name"]}"' for c in d["ciel"] if c["name"] and low in c["name"].lower()]
            if via:
                hits.append(dict(d, matched_via=via[0]))
        return sorted(hits, key=lambda d: d["name"].lower())


# --- command line ---
def fmt_drug(d):
    ciel = "; ".join(f"{c['code']} {c['name']}" for c in d["ciel"][:5])
    more = f" (+{len(d['ciel']) - 5} more)" if len(d["ciel"]) > 5 else ""
    rx = d["rxcui"] or "none (documented gap)"
    brands = d.get("brand_names", [])
    bmore = f" (+{len(brands) - 6} more)" if len(brands) > 6 else ""
    lines = [f"{d['name']}  [{d['id']}]",
             f"  RxCUI     {rx}" + (f"  ({d['rxnorm_name']})" if d["rxnorm_name"] else ""),
             f"  DrugBank  {d['drugbank_id'] or 'none'}",
             f"  ATC       {', '.join(d['atc']) or 'none'}",
             f"  Brands    {', '.join(brands[:6]) or 'none'}{bmore}",
             f"  CIEL      {ciel or 'none'}{more}"]
    if "partner_counts" in d:
        c = d["partner_counts"]
        lines.append(f"  Partners  {d['partners_total']} total: " + ", ".join(f"{c[s]} {s}" for s in SEVERITIES))
        c = d["condition_counts"]
        lines.append(f"  Conditions {d['conditions_total']} rated: " + ", ".join(f"{c[s]} {s}" for s in SEVERITIES if c[s])
                     if d["conditions_total"] else "  Conditions none on file")
    return "\n".join(lines)


def fmt_rec(r):
    mech = r["mechanism"] or "(no mechanism description on file)"
    return f"{r['severity']:<9}{r['drug_a']['name']} + {r['drug_b']['name']}\n         {mech}"


def fmt_cond(r):
    text = r["text"] or "(no description on file)"
    return f"{r['severity']:<9}{r['condition']}\n         {text}"


def fmt_derived(recs):
    if not recs:
        return []
    lines = ["Derived (condition-mediated; an inference from the drug-disease table, not a DDInter pairwise rating):"]
    for r in recs:
        lines.append(f"  {r['condition']}  ({r['basis']})")
        for side, d in (("a", r["drug_a"]), ("b", r["drug_b"])):
            row = r[side]
            text = (row["text"] or "(no description on file)")
            lines.append(f"    {d['name']:<24} {row['severity']:<9} {row['condition']}: {text[:150]}{'...' if len(text) > 150 else ''}")
    return lines


def gap(a, b):
    return f"No interaction on file for {a} + {b}. That is a knowledge gap, not a clearance."


def run(kb, args):
    """Returns (json_result, human_text) for the parsed command."""
    if args.cmd == "drug":
        drugs = kb.profile(args.term)
        return drugs, "\n\n".join(fmt_drug(d) for d in drugs)
    if args.cmd == "pair":
        recs, derived = kb.pair(args.a, args.b), kb.derived(args.a, args.b)
        lines = [fmt_rec(r) for r in recs] or [gap(args.a, args.b)]
        lines += fmt_derived(derived)
        return {"interactions": recs, "derived": derived}, "\n".join(lines)
    if args.cmd == "conditions":
        recs = kb.conditions(args.term)
        return recs, "\n".join(fmt_cond(r) for r in recs) or f"No disease interactions on file for {args.term}."
    if args.cmd == "check":
        res = kb.check(args.terms)
        lines = ["Checked: " + ", ".join(d["name"] for d in res["checked"])]
        lines += [fmt_rec(r) for r in res["interactions"]] or ["No interactions on file among these drugs (a gap, not a clearance)."]
        lines += fmt_derived(res["derived"])
        for u in res["unresolved"]:
            hint = f"  did you mean: {', '.join(u['suggestions'])}?" if u["suggestions"] else ""
            lines.append(f"Not in the knowledge base: {u['term']}{hint}")
        return res, "\n".join(lines)
    if args.cmd == "partners":
        recs = kb.partners(args.term, args.severity)
        shown = recs[:args.limit] if args.limit > 0 else recs
        lines = [f"{len(recs)} partner(s) for {args.term}" + (f" ({', '.join(args.severity)})" if args.severity else "")]
        for r in shown:
            mech = (r["mechanism"] or "(no mechanism description on file)")
            lines.append(f"{r['severity']:<9}{r['partner']['name']:<32} {mech[:100]}{'...' if len(mech) > 100 else ''}")
        if len(shown) < len(recs):
            lines.append(f"... and {len(recs) - len(shown)} more (raise --limit, or --limit 0 for all)")
        return shown, "\n".join(lines)
    if args.cmd == "mechanism":
        m = kb.mechanism(args.gid)
        if m is None:
            return None, f"No mechanism group {args.gid}."
        return m, f"group {m['group_id']}  [{', '.join(m['categories']) or 'no category'}]\n{m['text'] or '(sentinel: pairs listed without a mechanism description)'}"
    if args.cmd == "coverage":
        cov = kb.coverage()
        lines = ["| ATC | Group | Drugs | Interaction rows | In DDInter's bulk downloads |", "|---|---|---|---|---|"]
        for g in cov["groups"]:
            lines.append(f"| {g['atc']} | {g['group']} | {g['drugs']:,} | {g['interaction_rows']:,} | {'yes' if g['in_bulk_downloads'] else 'no'} |")
        lines.append(f"\nA row counts toward every group either drug belongs to. {cov['drugs_without_atc']} drugs carry no ATC code.")
        return cov, "\n".join(lines)
    if args.cmd == "search":
        hits = kb.search(args.text)
        lines = [f"{d['name']:<40} rxcui:{d['rxcui'] or '-':<8} {d['id']:<14}"
                 + (f" via {d['matched_via']}" if d["matched_via"] else "") for d in hits]
        return hits, "\n".join(lines) or f"No drug name contains {args.text!r}."
    raise AssertionError(args.cmd)


def main(argv=None):
    p = argparse.ArgumentParser(description="Query the OpenMRS DDI knowledge base.",
                                epilog="Drug terms: a name (DDInter, RxNorm, or CIEL), or rxcui:11289 / ciel:86415 / drugbank:DB00682 / id:DDInter1951.")
    p.add_argument("--kb", default=DEFAULT_KB, help="path to ddi_knowledge_base.json")
    p.add_argument("--json", action="store_true", help="machine-readable output")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("drug", help="a drug's identifiers, ATC, CIEL, and partner counts").add_argument("term")
    s = sub.add_parser("pair", help="do two drugs interact?")
    s.add_argument("a"); s.add_argument("b")
    sub.add_parser("check", help="every interacting pair in a medication list").add_argument("terms", nargs="+")
    s = sub.add_parser("partners", help="a drug's interacting partners")
    s.add_argument("term")
    s.add_argument("--severity", action="append", choices=SEVERITIES, help="keep only this severity (repeatable)")
    s.add_argument("--limit", type=int, default=50, help="rows to show (0 = all)")
    sub.add_parser("conditions", help="a drug's disease interactions (DDInter drug-disease table)").add_argument("term")
    sub.add_parser("mechanism", help="a mechanism group's text and categories").add_argument("gid")
    sub.add_parser("search", help="drugs whose name contains text").add_argument("text")
    sub.add_parser("coverage", help="drugs and interaction rows per ATC group (markdown table)")
    args = p.parse_args(argv)

    kb = KB.load(args.kb)
    try:
        result, text = run(kb, args)
    except Unresolved as e:
        hint = f"  Did you mean: {', '.join(e.suggestions)}?" if e.suggestions else ""
        print(f"Not in the knowledge base: {e.term!r}.{hint}", file=sys.stderr)
        return 2
    except Ambiguous as e:
        print(f"{e.term!r} names {len(e.drugs)} drugs; pick one by id:", file=sys.stderr)
        for d in e.drugs:
            print(f"  id:{d['id']:<14} {d['name']}  (rxcui {d['rxcui']})", file=sys.stderr)
        return 2
    except ValueError as e:
        print(e, file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
