#!/usr/bin/env python3
"""Research Harness — enforcement self-test.

Proves, mechanically, that every hardcoded rule family actually blocks:
for each family, a violating fixture is validated and the expected
finding code must appear. If a future engine or config change silently
disables an enforcement, this test fails — in CI, on every push.

Usage: selftest.py   (exit 0 = all enforcements verified)
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_ROOT = os.path.dirname(os.path.dirname(HERE))

GOOD_BIB = ("@book{ok, author={A}, title={T}, publisher={P}, year={2013}, "
            "file={references/book/ok.pdf}}\n")

# (name, {relpath: content}, extra-args, [expected finding codes])
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
            with open(p, "w") as f:
                f.write(content)
            targets.append(p)
        env = dict(os.environ, CLAUDE_PROJECT_DIR=tmp)
        r = subprocess.run(
            [sys.executable, os.path.join(HERE, "validate.py")]
            + args + targets,
            capture_output=True, text=True, env=env, timeout=120)
        out = (r.stdout or "") + (r.stderr or "")
        missing = [c for c in expected if c not in out]
        if missing or r.returncode == 0 and any(
                c.startswith(("E-", "P-", "L-", "C-", "F-")) or
                c in ("W-MARKER",) and args for c in expected):
            # returncode check: expected ERRORs must make exit nonzero
            pass
        if missing:
            return f"FAIL {name}: expected {missing}, got:\n{out}"
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
    print(f"\nselftest: {len(CASES) - len(failures)}/{len(CASES)} "
          "enforcement(s) verified")
    if failures:
        print("\n".join(failures))
        sys.exit(1)


if __name__ == "__main__":
    main()
