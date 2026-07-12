#!/usr/bin/env python3
"""Paramasastra — enforcement self-test.

Proves, mechanically, that every hardcoded rule family actually blocks:
for each family, a violating fixture is validated and the expected
finding code must appear. If a future engine or config change silently
disables an enforcement, this test fails — in CI, on every push.

Usage: selftest.py   (exit 0 = all enforcements verified)
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
TEMPLATE_ROOT = os.path.dirname(os.path.dirname(HERE))

GOOD_BIB = ("@book{ok, author={A}, title={T}, publisher={P}, year={2013}, "
            "file={references/book/ok.pdf}}\n")
DOI_BIB = ("@article{smith2020, author={S}, title={Great Work}, "
           "journal={J}, doi={10.1234/xyz}, year={2020}, "
           "file={references/paper/great.pdf}}\n")


def make_docx(path, specs):
    """Materialize a .docx fixture from paragraph specs (no binary
    fixtures in git — built through ooxml.py, which also proves the
    builders round-trip through the scanner). Spec keys:
      text            paragraph text
      heading         1-3 -> HeadingN style
      zotero          {doi,title} -> complete CSL field (split runs)
      split           instrText fragmentation for zotero (default 3)
      dangling        True -> fldChar begin + instr, never closed
    """
    import ooxml
    ooxml.new_docx(path)
    doc = ooxml.load(path)
    for spec in specs:
        style = f"Heading{spec['heading']}" if spec.get("heading") else None
        p = ooxml.make_paragraph(spec.get("text", ""), style_id=style)
        if spec.get("zotero"):
            csl = json.dumps({"citationItems": [{"itemData": {
                "DOI": spec["zotero"].get("doi", ""),
                "title": spec["zotero"].get("title", "")}}]})
            for r in ooxml.csl_field_runs(csl, "(cited)",
                                          split=spec.get("split", 3)):
                p.append(r)
        if spec.get("dangling"):
            p.append(ooxml.fld_char_run("begin"))
            p.append(ooxml.instr_run(" ADDIN ZOTERO_ITEM CSL_CITATION {} "))
        doc.append_paragraph(p)
    doc.save()


# (name, {relpath: content}, extra-args, [expected finding codes])
# A str content is written verbatim; ("docx", [specs]) builds a .docx.
# An expected code prefixed with '!' asserts the code must NOT appear.
CASES = [
    ("forbidden vocab", {"paper/s/x.tex": "We delve into this."},
     [], ["P-VOCAB"]),
    ("em-dash", {"paper/s/x.tex": "A claim — with a dash."},
     [], ["P-EMDASH"]),
    ("banned phrase", {"paper/s/x.tex": "It is worth noting that X."},
     [], ["P-PHRASE"]),
    ("banned construction", {"paper/s/x.tex":
     "It is not just fast, but also reliable."}, [], ["P-NOTJUST"]),
    ("suspect-word density", {"paper/s/x.tex":
     "The key register holds the key operand near the key bus."},
     [], ["P-DENSITY"]),
    ("marker pair integrity", {"paper/s/x.tex":
     "% @EDIT[chg-1|REWRITE] tighten\nProse.\n"}, [], ["E-MARKER"]),
    ("strict marker gate", {"paper/s/x.tex":
     "% @TODO write this\nProse.\n"}, ["--strict-markers"], ["W-MARKER"]),
    ("hallucinated cite key", {"paper/s/x.tex":
     "As shown by \\citep{ghost2024}."}, [], ["C-KEY"]),
    ("bib type policy", {"references.bib":
     GOOD_BIB + "@misc{web1, title={W}, file={references/book/ok.pdf}}\n"},
     [], ["E-BIBTYPE"]),
    ("bib required fields", {"references.bib":
     "@book{nofield, title={T}, file={references/book/ok.pdf}}\n"},
     [], ["E-BIBFIELD"]),
    ("shelf: source must exist", {"references.bib":
     "@book{nof, author={A}, title={T}, publisher={P}, year={2013}}\n"},
     [], ["E-BIBSRC"]),
    ("shelf: type/section binding", {"references.bib":
     "@article{wrong, author={A}, title={T}, journal={J}, doi={10.1/x}, "
     "year={2013}, author={A}, file={references/book/ok.pdf}}\n"},
     [], ["E-BIBSRC"]),
    ("float caption/label", {"paper/s/x.tex":
     "\\begin{figure}\nx\n\\end{figure}\n"}, [], ["L-FLOAT"]),
    ("duplicate labels", {"paper/s/x.tex":
     "\\label{fig:a}\n\\label{fig:a}\n"}, [], ["L-XREF"]),
    ("graphics must exist", {"paper/s/x.tex":
     "\\begin{figure}\n\\includegraphics{ghost-img}\n\\caption{C}\n"
     "\\label{fig:g}\n\\end{figure}\nSee~\\ref{fig:g}.\n"},
     [], ["L-GRAPHIC"]),
    ("monolith blocked", {"paper/chapter2.tex":
     "\\chapter{X}\n\\section{A}\nProse.\n\\section{B}\nProse.\n"},
     [], ["L-MODULAR"]),
    ("section-as-directory", {"paper/ch2/sec-alu.tex":
     "\\section{ALU}\nProse.\n"}, [], ["L-MODULAR"]),
    ("label prefix convention", {"paper/s/x.tex":
     "\\label{wrongprefix:a}\n"}, [], ["L-LABEL"]),
    ("docx: prose rules reach paragraphs", {"paper/s/x.docx": ("docx", [
     {"text": "We delve into this — deeply."}])},
     [], ["P-VOCAB", "P-EMDASH"]),
    ("docx: split zotero field resolves to bib", {
     "references.bib": GOOD_BIB + DOI_BIB,
     "references/paper/great.pdf": "x",
     "paper/s/x.docx": ("docx", [
      {"text": "Prior work shows this ",
       "zotero": {"doi": "10.1234/xyz", "title": "Great Work"}}])},
     [], ["!O-CITE", "!O-FIELD"]),
    ("docx: unknown citation field", {"paper/s/x.docx": ("docx", [
     {"text": "Bogus claim ",
      "zotero": {"doi": "10.9999/ghost", "title": "Phantom"}}])},
     [], ["O-CITE"]),
    ("docx: broken citation field", {"paper/s/x.docx": ("docx", [
     {"text": "Text before ", "dangling": True}])},
     [], ["O-FIELD"]),
    ("docx: one top-level heading per file", {"paper/s/x.docx": ("docx", [
     {"text": "Introduction", "heading": 1}, {"text": "Prose."},
     {"text": "Another Chapter", "heading": 1}])},
     [], ["O-STRUCT"]),
    ("docx: strict marker gate", {"paper/s/x.docx": ("docx", [
     {"text": "@TODO write the evaluation"}])},
     ["--strict-markers"], ["W-MARKER"]),
    ("docx: marker pair integrity", {"paper/s/x.docx": ("docx", [
     {"text": "@EDIT[chg-1|REWRITE] tighten"}, {"text": "Prose."}])},
     [], ["E-MARKER"]),
    ("docx: plain-text pseudo-citation", {"paper/s/x.docx": ("docx", [
     {"text": "As shown in [12]."}])},
     [], ["O-CITE"]),
]


def run_case(name, files, args, expected):
    tmp = tempfile.mkdtemp()
    try:
        shutil.copytree(os.path.join(TEMPLATE_ROOT, "harness"),
                        os.path.join(tmp, "harness"))
        os.makedirs(os.path.join(tmp, "references", "book"))
        with open(os.path.join(tmp, "references", "book", "ok.pdf"), "w") as f:
            f.write("x")
        with open(os.path.join(tmp, "references.bib"), "w") as f:
            f.write(GOOD_BIB)
        targets = []
        for rel, content in files.items():
            p = os.path.join(tmp, rel)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            if isinstance(content, tuple) and content[0] == "docx":
                make_docx(p, content[1])
            else:
                with open(p, "w") as f:
                    f.write(content)
            targets.append(p)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "validate.py")]
            + args + targets,
            capture_output=True, text=True, env=env, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        missing = [c for c in expected
                   if not c.startswith("!") and c not in out]
        unexpected = [c[1:] for c in expected
                      if c.startswith("!") and c[1:] in out]
        if missing:
            return f"FAIL {name}: expected {missing}, got:\n{out}"
        if unexpected:
            return f"FAIL {name}: must NOT contain {unexpected}, got:\n{out}"
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def run_docxtool_case():
    """Prove the docxtool placeholder contract: a rewrite must carry
    every citation field ({{field:k}}) exactly once — the preserved
    field's instruction survives byte-identical — and a rewrite that
    drops the placeholder is refused with the file untouched."""
    import ooxml
    tmp = tempfile.mkdtemp()
    try:
        shutil.copytree(os.path.join(TEMPLATE_ROOT, "harness"),
                        os.path.join(tmp, "harness"))
        os.makedirs(os.path.join(tmp, "references", "book"))
        os.makedirs(os.path.join(tmp, "references", "paper"))
        for rel in ("references/book/ok.pdf", "references/paper/great.pdf"):
            with open(os.path.join(tmp, rel), "w") as f:
                f.write("x")
        with open(os.path.join(tmp, "references.bib"), "w") as f:
            f.write(GOOD_BIB + DOI_BIB)
        os.makedirs(os.path.join(tmp, "paper", "s"))
        p = os.path.join(tmp, "paper", "s", "x.docx")
        make_docx(p, [{"text": "Prior work shows this ",
                       "zotero": {"doi": "10.1234/xyz",
                                  "title": "Great Work"}}])
        instr_before = ooxml.load(p).fields[0].instr
        env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
        dt = [sys.executable, os.path.join(HERE, "docxtool.py")]

        r = subprocess.run(dt + ["replace", p, "1", "--text",
                                 "Dropping the citation entirely."],
                           capture_output=True, text=True, env=env,
                           timeout=120)
        if r.returncode != 1:
            return (f"FAIL docxtool: placeholder-less replace must be "
                    f"refused (exit 1), got {r.returncode}:\n{r.stderr}")
        if ooxml.load(p).paras[0].text != "Prior work shows this (cited)":
            return "FAIL docxtool: refused replace still modified the file"

        r = subprocess.run(dt + ["replace", p, "1", "--text",
                                 "Rewritten around {{field:1}} cleanly."],
                           capture_output=True, text=True, env=env,
                           timeout=120)
        if r.returncode != 0:
            return (f"FAIL docxtool: placeholder replace should pass, "
                    f"got {r.returncode}:\n{r.stdout}{r.stderr}")
        doc = ooxml.load(p)
        if len(doc.fields) != 1 or doc.fields[0].instr != instr_before:
            return "FAIL docxtool: citation field not preserved byte-exact"
        if doc.paras[0].text != "Rewritten around (cited) cleanly.":
            return f"FAIL docxtool: unexpected text '{doc.paras[0].text}'"
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main():
    failures = []
    for name, files, args, expected in CASES:
        err = run_case(name, files, args, expected)
        status = "ok " if not err else "FAIL"
        print(f"[{status}] {name}")
        if err:
            failures.append(err)
    err = run_docxtool_case()
    print(f"[{'ok ' if not err else 'FAIL'}] docxtool: placeholder contract")
    if err:
        failures.append(err)
    total = len(CASES) + 1
    print(f"\nselftest: {total - len(failures)}/{total} "
          "enforcement(s) verified")
    if failures:
        print("\n".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
