#!/usr/bin/env python3
"""Paramasastra — citation existence verifier (anti-hallucination).

Offline mode (default, used by hooks/pre-commit):
    * every configured bib file parses
    * required fields present (delegated to validate.py, repeated here
      for standalone use)

Online mode (--online, used by CI / on demand):
    * every DOI resolves via Crossref and the fetched title fuzzy-matches
      the bib title  -> a fabricated reference cannot pass
    * every ISBN resolves via OpenLibrary
    * results cached in .harness/cache/citecheck.json for cache_days

Exit codes: 0 = verified, 1 = failures.
Requires only the Python standard library.
"""
import argparse
import difflib
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import (repo_root, load_config, parse_bibs,  # noqa: E402
                      collect_all, relpath)

UA = {"User-Agent": "paramasastra-citecheck/1.0 (mailto:none@example.com)"}


def norm_title(t):
    return re.sub(r"[^a-z0-9 ]", "", re.sub(r"[{}\\]", "", t.lower())).strip()


def similar(a, b):
    return difflib.SequenceMatcher(None, norm_title(a), norm_title(b)).ratio()


def fetch_json(url, timeout=20):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def load_cache(root):
    p = os.path.join(root, ".harness", "cache", "citecheck.json")
    try:
        with open(p) as f:
            return json.load(f)
    except Exception:
        return {}


def save_cache(root, cache):
    d = os.path.join(root, ".harness", "cache")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "citecheck.json"), "w") as f:
        json.dump(cache, f, indent=1)


def verify_doi(doi, title, threshold):
    url = "https://api.crossref.org/works/" + urllib.parse.quote(doi)
    try:
        data = fetch_json(url)
    except Exception as e:
        return False, f"DOI '{doi}' did not resolve on Crossref ({e})"
    fetched = " ".join(data.get("message", {}).get("title", []) or [""])
    if title and fetched and similar(title, fetched) < threshold:
        return False, (f"DOI '{doi}' resolves, but Crossref title "
                       f"'{fetched[:80]}' does not match bib title "
                       f"'{title[:80]}' — key may point to the wrong work")
    return True, "ok"


def verify_isbn(isbn, title, threshold):
    clean = re.sub(r"[^0-9Xx]", "", isbn)
    url = f"https://openlibrary.org/isbn/{clean}.json"
    try:
        data = fetch_json(url)
    except Exception as e:
        return False, f"ISBN '{isbn}' did not resolve on OpenLibrary ({e})"
    fetched = data.get("title", "")
    if title and fetched and similar(title, fetched) < threshold:
        return False, (f"ISBN '{isbn}' resolves, but OpenLibrary title "
                       f"'{fetched[:80]}' does not match bib title "
                       f"'{title[:80]}'")
    return True, "ok"


def report_docx(root, cfg):
    """Offline audit: every native citation field across the governed
    .docx manuscripts with its bib match status. The validator already
    fails on O-CITE/O-FIELD; this is the human-readable overview."""
    import ooxml
    th = float(cfg.get("docx", {}).get("citations", {})
               .get("title_match_threshold", 0.85))
    _, entries = parse_bibs(root, cfg)
    failures = total = 0
    for f in collect_all(root, cfg):
        if not f.lower().endswith(".docx") or \
                os.path.basename(f).startswith("~$"):
            continue
        rel = relpath(root, f)
        try:
            doc = ooxml.load(f)
        except ooxml.DocxError as e:
            print(f"[FAIL] {rel}: {e}")
            failures += 1
            continue
        for fld in doc.fields:
            total += 1
            loc = ("footnote" if fld.location == "footnote"
                   else f"para {fld.para_index}")
            ident = "; ".join((i.get("doi") or i.get("isbn")
                               or (i.get("title") or "")[:50] or "?")
                              for i in fld.items) or fld.tag or "?"
            if fld.broken:
                print(f"[FAIL] {rel} {loc}: BROKEN field ({fld.reason})")
                failures += 1
                continue
            keys = [match_bib_key for match_bib_key, _ in
                    (ooxml.match_bib(i, entries, th)
                     for i in (fld.items or [{}]))]
            if all(keys):
                print(f"[PASS] {rel} {loc}: {ident} -> {', '.join(keys)}")
            else:
                print(f"[FAIL] {rel} {loc}: {ident} -> UNMATCHED "
                      "(no references.bib entry)")
                failures += 1
    print(f"citecheck --docx: {total} field(s), {failures} failure(s)")
    sys.exit(1 if failures else 0)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--online", action="store_true",
                    help="verify DOIs/ISBNs against Crossref/OpenLibrary")
    ap.add_argument("--docx", action="store_true",
                    help="audit native citation fields in governed .docx "
                         "manuscripts against the bib (offline)")
    args = ap.parse_args()

    root = repo_root()
    cfg = load_config(root)
    if args.docx:
        report_docx(root, cfg)
    cit = cfg.get("citations", {})
    von = cit.get("verify_online", {})
    threshold = float(von.get("title_match_threshold", 0.75))
    ttl = int(von.get("cache_days", 90)) * 86400

    _, entries = parse_bibs(root, cfg)
    failures = 0
    print(f"citecheck: {len(entries)} bib entr(ies) found")

    if not args.online:
        print("citecheck: offline mode — run with --online to verify "
              "DOIs/ISBNs against Crossref/OpenLibrary")
        sys.exit(0)

    if not von.get("enabled", True):
        print("citecheck: verify_online disabled in harness.json")
        sys.exit(0)

    cache = load_cache(root)
    now = time.time()
    for e in entries:
        f = e["fields"]
        title = f.get("title", "")
        ident = f.get("doi") or f.get("isbn")
        if not ident:
            continue  # required_fields policy handles missing identifiers
        ckey = f"{e['key']}::{ident}"
        hit = cache.get(ckey)
        if hit and now - hit["t"] < ttl:
            ok, msg = hit["ok"], hit["msg"]
        else:
            if f.get("doi"):
                ok, msg = verify_doi(f["doi"], title, threshold)
            else:
                ok, msg = verify_isbn(f["isbn"], title, threshold)
            cache[ckey] = {"ok": ok, "msg": msg, "t": now}
            time.sleep(0.5)  # be polite to the APIs
        status = "PASS" if ok else "FAIL"
        print(f"[{status}] {e['key']}: {msg}")
        if not ok:
            failures += 1

    save_cache(root, cache)
    print(f"citecheck: {failures} failure(s)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
