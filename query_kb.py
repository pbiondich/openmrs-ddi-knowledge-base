"""
query_kb.py — ask the knowledge base a question from the command line.

Loads out/ddi_knowledge_base.json and does the three-table joins, so a question
takes one line instead of a script:

  python3 query_kb.py pair warfarin aspirin                do these two interact? severity + mechanism
  python3 query_kb.py check warfarin aspirin simvastatin   every interacting pair in a medication list
  python3 query_kb.py partners warfarin --severity Major   a drug's interacting partners, most severe first
  python3 query_kb.py drug warfarin                        identifiers, ATC, CIEL concepts, partner counts
  python3 query_kb.py mechanism 34                         a mechanism group's text and categories
  python3 query_kb.py search statin                        drugs whose name contains a string

Name a drug by its DDInter name, RxNorm name, or CIEL concept name (case-insensitive),
or by identifier with a prefix: rxcui:11289, ciel:86415, drugbank:DB00682, id:DDInter1951.
--json on any command prints machine-readable output; --kb PATH points at another file.

Importable: from query_kb import KB; kb = KB.load(); kb.pair("warfarin", "aspirin").
A pair with no record is a knowledge gap, never a clearance (see README).
"""
import argparse, difflib, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DEFAULT_KB = os.path.join(HERE, "out", "ddi_knowledge_base.json")
SEVERITIES = ["Major", "Moderate", "Minor", "Unknown"]
RANK = {s: i for i, s in enumerate(SEVERITIES)}
PREFIXES = ("rxcui", "ciel", "drugbank", "id")


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
        # --- name indexes, in precedence order: DDInter name, RxNorm name, CIEL concept name ---
        self.by_name, self.by_rxname, self.by_cielname = {}, {}, {}
        for d in self.drugs:
            self.by_name.setdefault(d["name"].lower(), []).append(d)
            if d["rxnorm_name"]:
                self.by_rxname.setdefault(d["rxnorm_name"].lower(), []).append(d)
            for c in d["ciel"]:
                if c["name"]:
                    self.by_cielname.setdefault(c["name"].lower(), []).append(d)
        self.all_names = sorted(set(self.by_name) | set(self.by_rxname))
        # --- interaction indexes: one row per unordered pair; partners per drug ---
        self.rows, self.partners_of = {}, {}
        for a, b, sev, gid in data["interactions"]:
            self.rows[(a, b) if a <= b else (b, a)] = (sev, gid)
            self.partners_of.setdefault(a, []).append((b, sev, gid))
            if a != b:
                self.partners_of.setdefault(b, []).append((a, sev, gid))

    @classmethod
    def load(cls, path=DEFAULT_KB):
        with open(path) as f:
            return cls(json.load(f))

    # --- resolution ---
    def resolve(self, term):
        """All drugs a term names. Identifier prefixes are exact; a bare name tries the DDInter
        name, then the RxNorm name, then CIEL concept names. Raises Unresolved when nothing matches."""
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
        for index in (self.by_name, self.by_rxname, self.by_cielname):
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

    def check(self, terms):
        """Every interacting pair among a medication list, most severe first, plus the terms
        that could not be resolved, so a gap is reported rather than swallowed."""
        resolved, unresolved = [], []
        for t in terms:
            try:
                resolved.extend(self.resolve(t))
            except Unresolved as e:
                unresolved.append({"term": t, "suggestions": e.suggestions})
        found = []
        for i in range(len(resolved)):
            for j in range(i + 1, len(resolved)):
                a, b = resolved[i], resolved[j]
                rec = self.interaction(a, b) if a["id"] != b["id"] else None
                if rec:
                    found.append(rec)
        found.sort(key=lambda r: (RANK[r["severity"]], r["drug_a"]["name"], r["drug_b"]["name"]))
        return {"checked": [brief(d) for d in resolved], "interactions": found, "unresolved": unresolved}

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
            out.append(dict(d, partner_counts=counts, partners_total=sum(counts.values())))
        return out

    def search(self, text):
        """Drugs whose DDInter, RxNorm, or CIEL name contains the text. A hit found only through a
        CIEL combination name (say "Imipenem / cilastatin" for "statin") carries that name in
        matched_via, so the reader can see why an unexpected drug is in the list."""
        low = text.lower()
        hits = []
        for d in self.drugs:
            if low in d["name"].lower() or (d["rxnorm_name"] and low in d["rxnorm_name"].lower()):
                hits.append(dict(d, matched_via=None))
                continue
            via = [c["name"] for c in d["ciel"] if c["name"] and low in c["name"].lower()]
            if via:
                hits.append(dict(d, matched_via=via[0]))
        return sorted(hits, key=lambda d: d["name"].lower())


# --- command line ---
def fmt_drug(d):
    ciel = "; ".join(f"{c['code']} {c['name']}" for c in d["ciel"][:5])
    more = f" (+{len(d['ciel']) - 5} more)" if len(d["ciel"]) > 5 else ""
    rx = d["rxcui"] or "none (documented gap)"
    lines = [f"{d['name']}  [{d['id']}]",
             f"  RxCUI     {rx}" + (f"  ({d['rxnorm_name']})" if d["rxnorm_name"] else ""),
             f"  DrugBank  {d['drugbank_id'] or 'none'}",
             f"  ATC       {', '.join(d['atc']) or 'none'}",
             f"  CIEL      {ciel or 'none'}{more}"]
    if "partner_counts" in d:
        c = d["partner_counts"]
        lines.append(f"  Partners  {d['partners_total']} total: " + ", ".join(f"{c[s]} {s}" for s in SEVERITIES))
    return "\n".join(lines)


def fmt_rec(r):
    mech = r["mechanism"] or "(no mechanism description on file)"
    return f"{r['severity']:<9}{r['drug_a']['name']} + {r['drug_b']['name']}\n         {mech}"


def gap(a, b):
    return f"No interaction on file for {a} + {b}. That is a knowledge gap, not a clearance."


def run(kb, args):
    """Returns (json_result, human_text) for the parsed command."""
    if args.cmd == "drug":
        drugs = kb.profile(args.term)
        return drugs, "\n\n".join(fmt_drug(d) for d in drugs)
    if args.cmd == "pair":
        recs = kb.pair(args.a, args.b)
        return recs, "\n".join(fmt_rec(r) for r in recs) if recs else gap(args.a, args.b)
    if args.cmd == "check":
        res = kb.check(args.terms)
        lines = ["Checked: " + ", ".join(d["name"] for d in res["checked"])]
        lines += [fmt_rec(r) for r in res["interactions"]] or ["No interactions on file among these drugs (a gap, not a clearance)."]
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
    if args.cmd == "search":
        hits = kb.search(args.text)
        lines = [f"{d['name']:<40} rxcui:{d['rxcui'] or '-':<8} {d['id']:<14}"
                 + (f" via CIEL \"{d['matched_via']}\"" if d["matched_via"] else "") for d in hits]
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
    sub.add_parser("mechanism", help="a mechanism group's text and categories").add_argument("gid")
    sub.add_parser("search", help="drugs whose name contains text").add_argument("text")
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
