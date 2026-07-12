#!/usr/bin/env python3
"""Paramasastra — the ONLY sanctioned way to edit a .docx manuscript.

A .docx is a zip of XML; Edit/Write would corrupt it, so the pre-tool
gate blocks them and the AI drives this CLI instead. Every mutation is
whole-paragraph (never sub-run surgery), self-gated (branch gate +
protected paths, refuses Word-locked files) and self-validating (the
validator runs on the file after every edit — the same contract the
PostToolUse hook enforces for Edit/Write).

Read commands (no gating):
    cat FILE [--from N] [--to M] [--json]   numbered paragraphs;
                                            [H1]/[MARKER] tags
    show FILE N          one paragraph in detail: text with {{field:k}}
                         placeholders, style, outline level, fields
    outline FILE         heading tree with paragraph indices
    cites FILE [--json]  all citation fields: matched bib key /
                         UNMATCHED / BROKEN

Mutating commands (gated + validated):
    replace FILE N --text "..."   PLACEHOLDER CONTRACT: if the paragraph
                                  contains citation fields, the new text
                                  must reference every {{field:k}}
                                  exactly once — the preserved field XML
                                  is spliced back, so a rewrite cannot
                                  silently drop a citation.
    insert FILE N --text "..." [--before] [--heading L | --style ID]
                               [--marker]  (N=0: append at document end)
    delete FILE N [--to M]
    add-cite FILE N --key BIBKEY [--prefix "..."]
                     synthesizes a Zotero-compatible CSL field from the
                     bib entry. CAVEAT: Zotero may need to re-link the
                     item on its next refresh; the visible "(Author,
                     Year)" is this tool's formatted guess. Disable via
                     docx.citations.allow_generated_fields=false and
                     leave @TODOCITE markers for the human instead.
    new FILE [--title "..."]

Exit codes: 0 = success and validation clean;
            1 = usage/tool/gate error, NO edit applied;
            2 = edit applied but the file now FAILS validation — the
                findings on stderr must be fixed before proceeding.
"""
import argparse
import copy
import json
import os
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import ooxml  # noqa: E402
from ooxml import w  # noqa: E402
from validate import (repo_root, load_config, relpath, norm,  # noqa: E402
                      parse_bibs)

PLACEHOLDER = re.compile(r"\{\{field:(\d+)\}\}")


def die(msg):
    print(f"docxtool: {msg}", file=sys.stderr)
    sys.exit(1)


# ------------------------------------------------------------ gating


def gate_mutation(root, cfg, path):
    """Same contract the hooks enforce for Edit/Write: protected paths,
    feature-branch gate, and never touch a file Word has open."""
    rel = relpath(root, path)
    pp = cfg.get("protected_paths", {})
    if os.environ.get(pp.get("override_env", "ALLOW_PROTECTED")) != "1":
        for d in pp.get("deny", []):
            if rel.startswith(norm(d)):
                die(f"BLOCKED (protected_paths.deny): '{d}' must not be "
                    "modified")
    git = cfg.get("git", {})
    if git.get("enabled", True) and git.get("require_feature_branch", True) \
            and not any(rel.startswith(norm(x))
                        for x in git.get("exempt_paths", [])):
        try:
            b = subprocess.run(["git", "-C", root, "branch",
                                "--show-current"], capture_output=True,
                               text=True, timeout=10).stdout.strip()
        except Exception:
            b = ""
        if b in git.get("protected_branches", ["main", "master"]):
            die(f"BLOCKED (git.require_feature_branch): you are on '{b}'. "
                "Create a feature branch first (git checkout -b "
                f"{'|'.join(git.get('branch_prefixes', ['feat/']))}<topic>)")
    d = os.path.dirname(os.path.abspath(path))
    base = os.path.basename(path)
    for lock in ("~$" + base, "~$" + base[2:] if len(base) > 2 else ""):
        if lock and os.path.exists(os.path.join(d, lock)):
            die(f"'{base}' is open in Word (owner lock '{lock}' present) — "
                "close it there first")


def validate_after(root, cfg, path):
    """Run the validator on the edited file; block exactly like the
    PostToolUse hook (exit 2, findings on stderr)."""
    pe = cfg.get("enforcement", {}).get("post_edit", {})
    if not pe.get("enabled", True):
        return 0
    r = subprocess.run([sys.executable, os.path.join(HERE, "validate.py"),
                        path], capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and pe.get("block_on_error", True):
        print("docxtool: edit APPLIED but the file now FAILS validation. "
              "Fix every [ERROR] before proceeding:\n" + out,
              file=sys.stderr)
        return 2
    if "[WARN]" in out or r.returncode != 0:
        print("docxtool: validation findings (non-blocking):\n" + out)
    return 0


# ------------------------------------------------------------ rendering


def is_marker_para(para, cfg):
    mk = cfg.get("workflow", {}).get("markers", {})
    tokens = [mk.get("todo"), mk.get("cite"), mk.get("edit")]
    for key in ("original_begin", "original_end",
                "delete_begin", "delete_end"):
        t = mk.get(key)
        if t:
            tokens.append(t.split("{id}")[0].strip())
    return any(t and t in para.text for t in tokens if t)


def display_text(para):
    """Paragraph text with citation fields as {{field:k}} placeholders."""
    out, k = [], 0
    for kind, v in para.segments:
        if kind == "t":
            out.append(v)
        elif v.is_citation and not v.broken:
            k += 1
            out.append("{{field:%d}}" % k)
        else:
            out.append(v.result or "")
    return "".join(out), k


def para_tags(para, cfg):
    tags = []
    if para.outline_level:
        tags.append(f"H{para.outline_level}")
    if is_marker_para(para, cfg):
        tags.append("MARKER")
    return tags


def para_json(para, cfg, entries, threshold):
    text, nfields = display_text(para)
    return {"index": para.index, "text": text, "plain": para.text,
            "style": para.style_id, "level": para.outline_level,
            "marker": is_marker_para(para, cfg),
            "fields": [field_json(f, entries, threshold)
                       for f in para.cite_segments()]}


def field_json(fld, entries, threshold):
    d = {"kind": fld.kind, "broken": fld.broken, "result": fld.result}
    if fld.kind == "word":
        d["tag"] = fld.tag
    d["items"] = fld.items
    if entries is not None and not fld.broken:
        matches = [ooxml.match_bib(i, entries, threshold)
                   for i in (fld.items or [])]
        d["matched"] = [m[0] for m in matches]
    return d


# ------------------------------------------------------------ commands


def get_para(doc, n):
    if not 1 <= n <= len(doc.paras):
        die(f"paragraph {n} out of range (document has {len(doc.paras)})")
    return doc.paras[n - 1]


def cmd_cat(doc, args, cfg, entries, threshold):
    lo = args.frm or 1
    hi = args.to or len(doc.paras)
    paras = [p for p in doc.paras if lo <= p.index <= hi]
    if args.json:
        print(json.dumps([para_json(p, cfg, entries, threshold)
                          for p in paras], indent=1))
        return
    for p in paras:
        text, _ = display_text(p)
        tags = "".join(f"[{t}]" for t in para_tags(p, cfg))
        print(f"{p.index}:{(' ' + tags) if tags else ''} {text}")


def cmd_show(doc, args, cfg, entries, threshold):
    p = get_para(doc, args.n)
    info = para_json(p, cfg, entries, threshold)
    print(json.dumps(info, indent=1))
    if p.mixed_format:
        print("NOTE: this paragraph has mixed character formatting — "
              "'replace' flattens it to the first run's format "
              "(requires --force-flatten).", file=sys.stderr)


def cmd_outline(doc, args, cfg, entries, threshold):
    for p in doc.paras:
        if p.outline_level:
            print(f"{'  ' * (p.outline_level - 1)}H{p.outline_level} "
                  f"[{p.index}] {p.text}")


def cmd_cites(doc, args, cfg, entries, threshold):
    rows = []
    for fld in doc.fields:
        if fld.broken:
            status = f"BROKEN ({fld.reason})"
        elif entries is None:
            status = "no bib configured"
        else:
            keys = [ooxml.match_bib(i, entries, threshold)[0]
                    for i in (fld.items or [{}])]
            status = ", ".join(k if k else "UNMATCHED" for k in keys)
        ident = "; ".join((i.get("doi") or i.get("isbn")
                           or (i.get("title") or "")[:50] or "?")
                          for i in fld.items) or fld.tag or "?"
        rows.append({"para": fld.para_index, "kind": fld.kind,
                     "location": fld.location, "ident": ident,
                     "status": status, "result": fld.result})
    if args.json:
        print(json.dumps(rows, indent=1))
        return
    if not rows:
        print("no citation fields")
    for r in rows:
        loc = ("footnote" if r["location"] == "footnote"
               else f"para {r['para']}")
        print(f"{loc}: [{r['kind']}] {r['ident']} -> "
              f"{r['status']}  ({r['result']})")


def first_rpr(para):
    for r in para.element.iter(w("r")):
        rpr = r.find(w("rPr"))
        if rpr is not None:
            return copy.deepcopy(rpr)
    return None


def cmd_replace(doc, args, cfg, entries, threshold):
    p = get_para(doc, args.n)
    if any(f.broken for f in p.fields):
        die(f"paragraph {args.n} contains a BROKEN citation field — "
            "repair it in Word/Zotero before editing this paragraph")
    flds = p.cite_segments()
    if len(flds) != len([f for f in p.fields if not f.broken]):
        die(f"paragraph {args.n} contains a citation field this tool "
            "cannot preserve through a rewrite (nested or non-contiguous) "
            "— edit it in Word instead")
    refs = [int(m) for m in PLACEHOLDER.findall(args.text)]
    want = list(range(1, len(flds) + 1))
    if sorted(refs) != want:
        got = refs or "none"
        die(f"placeholder contract: paragraph {args.n} has {len(flds)} "
            f"citation field(s); --text must reference "
            f"{['{{field:%d}}' % i for i in want]} exactly once each "
            f"(got: {got}). Run 'show' to see the current placeholders — "
            "citations cannot be dropped or duplicated by a rewrite.")
    if p.mixed_format and not args.force_flatten:
        die(f"paragraph {args.n} has mixed character formatting "
            "(bold/italic spans would be flattened). Re-run with "
            "--force-flatten to accept, or edit in Word.")
    # capture preserved field XML before clearing
    children = list(p.element)
    preserved = {}
    for i, fld in enumerate(flds, 1):
        s, e = fld.child_span
        preserved[i] = children[s:e + 1]
    rpr = first_rpr(p)
    ppr = p.element.find(w("pPr"))
    for child in children:
        if child is not ppr:
            p.element.remove(child)
    pos = 0
    for m in PLACEHOLDER.finditer(args.text):
        if m.start() > pos:
            p.element.append(ooxml.make_run(
                args.text[pos:m.start()],
                copy.deepcopy(rpr) if rpr is not None else None))
        for el in preserved[int(m.group(1))]:
            p.element.append(el)
        pos = m.end()
    if pos < len(args.text):
        p.element.append(ooxml.make_run(
            args.text[pos:], copy.deepcopy(rpr) if rpr is not None else None))
    doc.save()
    print(f"replaced paragraph {args.n} "
          f"({len(flds)} citation field(s) preserved)")
    return validate_after(repo_root(), cfg, doc.path)


def cmd_insert(doc, args, cfg, entries, threshold):
    style = None
    if args.heading:
        if not 1 <= args.heading <= 3:
            die("--heading must be 1..3")
        style = f"Heading{args.heading}"
    if args.style:
        style = args.style
    if args.marker:
        style = cfg.get("docx", {}).get("markers", {}).get(
            "style", "HarnessMarker")
        doc.ensure_style(style, ooxml.MARKER_STYLE_XML.replace(
            "{style_id}", style))
    p = ooxml.make_paragraph(args.text, style_id=style)
    if args.n == 0 or not doc.paras:
        doc.append_paragraph(p)
    else:
        doc.insert_paragraph(p, get_para(doc, args.n), before=args.before)
    doc.save()
    where = ("end" if args.n == 0 or not doc.paras else
             f"{'before' if args.before else 'after'} paragraph {args.n}")
    print(f"inserted at {where}")
    return validate_after(repo_root(), cfg, doc.path)


def cmd_delete(doc, args, cfg, entries, threshold):
    hi = args.to or args.n
    if hi < args.n:
        die("--to must be >= N")
    victims = [get_para(doc, i) for i in range(args.n, hi + 1)]
    lost = [f for p in victims for f in p.fields]
    for p in victims:
        doc.remove_paragraph(p)
    doc.save()
    note = (f" (removed {len(lost)} citation field(s) with them)"
            if lost else "")
    print(f"deleted paragraph(s) {args.n}..{hi}{note}")
    return validate_after(repo_root(), cfg, doc.path)


def bib_to_csl(entry):
    """Best-effort CSL item from a bib entry — enough for the harness
    matcher (DOI/ISBN/title) and for Zotero to re-link by identifier."""
    f = entry["fields"]
    item = {"id": entry["key"], "title": f.get("title", "")}
    if f.get("doi"):
        item["DOI"] = f["doi"]
    if f.get("isbn"):
        item["ISBN"] = f["isbn"]
    authors = []
    for a in re.split(r"\s+and\s+", f.get("author", "")):
        a = a.strip()
        if a:
            authors.append({"family": a.split(",")[0].strip()})
    if authors:
        item["author"] = authors
    year = re.sub(r"\D", "", f.get("year", ""))[:4]
    if year:
        item["issued"] = {"date-parts": [[int(year)]]}
    item["type"] = {"article": "article-journal", "book": "book",
                    "inproceedings": "paper-conference",
                    "incollection": "chapter"}.get(entry["type"], "document")
    return item


def cmd_add_cite(doc, args, cfg, entries, threshold):
    dc = cfg.get("docx", {}).get("citations", {})
    if not dc.get("allow_generated_fields", True):
        die("docx.citations.allow_generated_fields is false — leave a "
            "@TODOCITE marker instead and let the human insert the "
            "citation through Zotero")
    entry = next((e for e in (entries or []) if e["key"] == args.key), None)
    if entry is None:
        die(f"cite key '{args.key}' not found in the configured bib "
            "file(s) — a citation cannot be synthesized for a source "
            "that is not on the shelf")
    p = get_para(doc, args.n)
    item = bib_to_csl(entry)
    csl = json.dumps({
        "citationItems": [{"id": entry["key"], "itemData": item}],
        "properties": {"formattedCitation": "", "plainCitation": ""},
        "schema": "https://github.com/citation-style-language/schema/"
                  "raw/master/csl-citation.json"})
    family = (item.get("author") or [{}])[0].get("family", "?")
    year = (item.get("issued", {}).get("date-parts") or [["n.d."]])[0][0]
    result = f"({family}, {year})"
    if args.prefix:
        p.element.append(ooxml.make_run(args.prefix, first_rpr(p)))
    for r in ooxml.csl_field_runs(csl, result):
        p.element.append(r)
    doc.save()
    print(f"appended citation field for '{args.key}' to paragraph "
          f"{args.n}: {result}\nNOTE: Zotero may need to re-link this "
          "item on its next refresh; the visible text is a formatted "
          "guess until then.")
    return validate_after(repo_root(), cfg, doc.path)


def main():
    ap = argparse.ArgumentParser(
        prog="docxtool.py",
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, n_arg=False, **kw):
        sp = sub.add_parser(name, **kw)
        sp.add_argument("file")
        if n_arg:
            sp.add_argument("n", type=int)
        return sp

    sp = add("cat")
    sp.add_argument("--from", dest="frm", type=int)
    sp.add_argument("--to", type=int)
    sp.add_argument("--json", action="store_true")
    add("show", n_arg=True)
    add("outline")
    sp = add("cites")
    sp.add_argument("--json", action="store_true")
    sp = add("replace", n_arg=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--force-flatten", action="store_true")
    sp = add("insert", n_arg=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--before", action="store_true")
    sp.add_argument("--heading", type=int)
    sp.add_argument("--style")
    sp.add_argument("--marker", action="store_true")
    sp = add("delete", n_arg=True)
    sp.add_argument("--to", type=int)
    sp = add("add-cite", n_arg=True)
    sp.add_argument("--key", required=True)
    sp.add_argument("--prefix")
    sp = add("new")
    sp.add_argument("--title")
    args = ap.parse_args()

    root = repo_root()
    cfg = load_config(root)
    if not cfg.get("formats", {}).get("docx", False):
        die("formats.docx is not enabled in the harness config")
    threshold = float(cfg.get("docx", {}).get("citations", {})
                      .get("title_match_threshold", 0.85))
    try:
        _, entries = parse_bibs(root, cfg)
    except Exception:
        entries = None

    mutating = args.cmd in ("replace", "insert", "delete", "add-cite", "new")
    if mutating:
        gate_mutation(root, cfg, args.file)

    if args.cmd == "new":
        if os.path.exists(args.file):
            die(f"{args.file} already exists")
        ooxml.new_docx(args.file, title=args.title)
        print(f"created {args.file}")
        sys.exit(validate_after(root, cfg, args.file))

    if not os.path.isfile(args.file):
        die(f"{args.file} not found")
    try:
        doc = ooxml.load(args.file)
    except ooxml.DocxError as e:
        die(str(e))

    fn = {"cat": cmd_cat, "show": cmd_show, "outline": cmd_outline,
          "cites": cmd_cites, "replace": cmd_replace, "insert": cmd_insert,
          "delete": cmd_delete, "add-cite": cmd_add_cite}[args.cmd]
    rc = fn(doc, args, cfg, entries, threshold)
    sys.exit(rc or 0)


if __name__ == "__main__":
    main()
