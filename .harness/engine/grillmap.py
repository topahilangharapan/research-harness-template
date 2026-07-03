#!/usr/bin/env python3
"""Research Harness — defense coverage engine (used by the 'defend' skill).

Deterministically extracts every GRILLABLE UNIT from the manuscript —
section headings, cited claims, floats, the scope statement — assigns
stable IDs, and tracks examination coverage across sessions. This makes
defense preparation systematic instead of random: the skill asks the
questions, but WHAT must be covered and HOW MUCH has been covered is
arithmetic.

Usage:
    grillmap.py --map                 print all units as JSON
    grillmap.py --coverage            readiness report (uses coverage file)
    grillmap.py --record ID STATUS [--note TEXT]
                                      record a result: pass|partial|fail
    grillmap.py --file PATH           override coverage file location
                                      (default: notes/defense-coverage.json)

Unit IDs hash the unit's content (not line numbers), so they survive
unrelated edits; units whose content changed appear as new/uncovered and
old records are reported as stale.
"""
import argparse
import datetime
import hashlib
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import (repo_root, load_config, collect_all, relpath,  # noqa: E402
                      strip_latex_comment, CITE_LATEX, CITE_MD, LABEL_RE)

HEADING_TEX = re.compile(r"\\(chapter|section|subsection)\*?\{([^}]*)\}")
HEADING_MD = re.compile(r"^(#{1,3})\s+(.+)$")
FLOAT_PREFIXES = ("fig:", "tab:", "lst:", "eq:")


def uid(kind, key):
    return kind + "-" + hashlib.sha1(
        f"{kind}|{key}".encode()).hexdigest()[:8]


def extract_units(root, cfg):
    units = []
    scope = cfg.get("scope", {}).get("statement", "").strip()
    if scope and not scope.startswith("DESCRIBE"):
        units.append({"id": uid("scope", scope), "kind": "scope",
                      "file": "harness/50-scope.json", "line": 0,
                      "text": scope[:120],
                      "ask": "defend the research scope and boundaries"})
    for path in collect_all(root, cfg):
        rel = relpath(root, path)
        if not rel.endswith((".tex", ".md", ".qmd", ".Rmd")):
            continue
        if not os.path.isfile(path):
            continue
        kind = "tex" if rel.endswith(".tex") else "md"
        text = open(path, encoding="utf-8", errors="replace").read()
        for n, raw in enumerate(text.splitlines(), 1):
            line = strip_latex_comment(raw) if kind == "tex" else raw
            if kind == "tex":
                for m in HEADING_TEX.finditer(line):
                    units.append({
                        "id": uid("sec", f"{rel}|{m.group(2)}"),
                        "kind": "section", "file": rel, "line": n,
                        "text": m.group(2),
                        "ask": "explain this section's argument and its "
                               "role in the whole"})
            else:
                m = HEADING_MD.match(line)
                if m:
                    units.append({
                        "id": uid("sec", f"{rel}|{m.group(2)}"),
                        "kind": "section", "file": rel, "line": n,
                        "text": m.group(2).strip(),
                        "ask": "explain this section's argument and its "
                               "role in the whole"})
            keys = []
            if kind == "tex":
                for cm in CITE_LATEX.finditer(line):
                    keys += [k.strip() for k in cm.group(1).split(",")
                             if k.strip()]
            else:
                keys += CITE_MD.findall(line)
            for k in keys:
                units.append({
                    "id": uid("cite", f"{rel}|{k}|{line.strip()[:80]}"),
                    "kind": "claim", "file": rel, "line": n,
                    "text": f"[{k}] {line.strip()[:100]}",
                    "ask": "defend this claim: what exactly does the "
                           "cited source say, where, and does it support "
                           "the sentence as written?"})
            for lm in LABEL_RE.finditer(line):
                if lm.group(1).startswith(FLOAT_PREFIXES):
                    units.append({
                        "id": uid("float", lm.group(1)),
                        "kind": "float", "file": rel, "line": n,
                        "text": lm.group(1),
                        "ask": "explain this figure/table: what it shows, "
                               "how it was produced, why it is evidence"})
    # dedupe by id (same float labeled once, etc.)
    seen, out = set(), []
    for u in units:
        if u["id"] not in seen:
            seen.add(u["id"])
            out.append(u)
    return out


def load_cov(path):
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return {"records": {}}


def save_cov(path, cov):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(cov, f, indent=1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--map", action="store_true")
    ap.add_argument("--coverage", action="store_true")
    ap.add_argument("--record", nargs=2, metavar=("ID", "STATUS"))
    ap.add_argument("--note", default="")
    ap.add_argument("--file", default=None)
    args = ap.parse_args()

    root = repo_root()
    cfg = load_config(root)
    cov_path = args.file or os.path.join(root, "notes",
                                         "defense-coverage.json")
    units = extract_units(root, cfg)

    if args.map:
        print(json.dumps(units, indent=1))
        return

    if args.record:
        rid, status = args.record
        if status not in ("pass", "partial", "fail"):
            sys.exit("status must be pass|partial|fail")
        if rid not in {u["id"] for u in units}:
            sys.exit(f"unknown unit id '{rid}' — run --map; the "
                     "manuscript may have changed under this unit")
        cov = load_cov(cov_path)
        rec = cov["records"].setdefault(rid, {"attempts": 0})
        rec["attempts"] += 1
        rec["status"] = status
        rec["last"] = datetime.date.today().isoformat()
        if args.note:
            rec["note"] = args.note[:200]
        save_cov(cov_path, cov)
        print(f"recorded {rid}: {status} (attempt {rec['attempts']})")
        return

    # --coverage (default)
    cov = load_cov(cov_path)
    ids = {u["id"]: u for u in units}
    recs = cov["records"]
    stale = [r for r in recs if r not in ids]
    attempted = [i for i in ids if i in recs]
    passed = [i for i in attempted if recs[i].get("status") == "pass"]
    failed = [i for i in attempted if recs[i].get("status") == "fail"]
    by_kind = {}
    for u in units:
        k = u["kind"]
        by_kind.setdefault(k, [0, 0])
        by_kind[k][1] += 1
        if u["id"] in passed:
            by_kind[k][0] += 1
    print(f"defense coverage — {len(units)} unit(s), "
          f"{len(attempted)} attempted, {len(passed)} passed, "
          f"{len(failed)} FAILED, {len(stale)} stale record(s)")
    print(f"readiness: {100 * len(passed) // max(1, len(units))}% "
          "(passed / total)")
    for k, (p, t) in sorted(by_kind.items()):
        print(f"  {k:8s} {p}/{t}")
    weak = [ids[i] for i in failed]
    fresh = [u for u in units if u["id"] not in recs]
    if weak:
        print("\nFAILED — regrill first:")
        for u in weak[:10]:
            print(f"  {u['id']} {u['file']}:{u['line']} {u['text'][:70]}")
    if fresh:
        print(f"\nnever grilled ({len(fresh)}) — next targets:")
        for u in fresh[:10]:
            print(f"  {u['id']} [{u['kind']}] {u['file']}:{u['line']} "
                  f"{u['text'][:70]}")
    sys.exit(0)


if __name__ == "__main__":
    main()
