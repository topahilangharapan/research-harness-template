#!/usr/bin/env python3
"""Paramasastra — versioned, validation-gated builds.

Every build gets its own folder under build/ named
    <YYYY-MM-DD_HHMMSS>_v<N>
timestamp first, then a version number starting at v0 and incrementing.
The version is derived statelessly from existing folders (max + 1), so
there is no counter file to corrupt.

THE GATE: before compiling, the manuscript must pass the validator
(and, with --strict, the marker-free delivery gate). A PDF cannot be
produced from a manuscript that violates policy — the build is an
artifact of a clean state, recorded in manifest.json (version,
timestamp, git commit, validation status).

Usage:
    build.py                normal build (validate first)
    build.py --strict       submission build: markers are errors too
    build.py --force        build despite validation errors (LOUD;
                            recorded in the manifest as forced)
Config (harness/70-workflow.json -> workflow.build):
    command   compile command; {main} and {out} are substituted
    main      main .tex file
    dir       build root (default build/)
    validate_first  refuse to build on validator errors (default true)
"""
import argparse
import datetime
import json
import os
import re
import shlex
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import repo_root, load_config  # noqa: E402


def next_version(bdir):
    v = -1
    if os.path.isdir(bdir):
        for name in os.listdir(bdir):
            m = re.search(r"_v(\d+)$", name)
            if m:
                v = max(v, int(m.group(1)))
    return v + 1


def run_validator(root, strict):
    cmd = [sys.executable, os.path.join(HERE, "validate.py"), "--all"]
    if strict:
        cmd.append("--strict-markers")
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    return r.returncode == 0, (r.stdout or "") + (r.stderr or "")


def git_commit(root):
    try:
        r = subprocess.run(["git", "-C", root, "rev-parse", "--short", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                               capture_output=True, text=True,
                               timeout=10).stdout.strip()
        return r.stdout.strip() + ("+dirty" if dirty else "")
    except Exception:
        return "unknown"


def build_docx(root, cfg, b, main_docx, out_dir, version, stamp,
               validation, args):
    """Word build: copy the validated .docx into the versioned build
    folder (that snapshot is the submission artifact) and, when
    LibreOffice is available, also export a PDF via
    workflow.build.docx_command. No soffice => snapshot only, exit 0."""
    print(f"build v{version} -> {os.path.relpath(out_dir, root)}")
    src = os.path.join(root, main_docx)
    if not os.path.isfile(src):
        sys.exit(f"BUILD FAILED: main file '{main_docx}' not found")
    snap = os.path.join(out_dir, os.path.basename(main_docx))
    shutil.copy2(src, snap)

    pdf, exit_code, log = None, 0, ""
    if shutil.which("soffice"):
        cmd = b.get("docx_command",
                    "soffice --headless --convert-to pdf "
                    "--outdir {out} {main}").format(
            main=shlex.quote(main_docx), out=shlex.quote(out_dir))
        print(f"$ {cmd}")
        r = subprocess.run(cmd, shell=True, cwd=root,
                           capture_output=True, text=True, timeout=600)
        log = (r.stdout or "") + (r.stderr or "")
        exit_code = r.returncode
        pdfs = [f for f in os.listdir(out_dir) if f.endswith(".pdf")]
        pdf = pdfs[0] if pdfs else None
        if exit_code != 0 or not pdf:
            print("PDF conversion FAILED — snapshot kept; see build.log")
    else:
        log = "PDF conversion skipped: soffice (LibreOffice) not found\n"
        print("PDF conversion skipped: soffice not found — snapshot only")
    with open(os.path.join(out_dir, "build.log"), "w") as f:
        f.write(log)

    manifest = {
        "version": version,
        "timestamp": stamp,
        "git_commit": git_commit(root),
        "main": main_docx,
        "format": "docx",
        "validation": validation,
        "strict": args.strict,
        "forced": args.force and validation == "FAILED",
        "exit_code": exit_code,
        "docx": os.path.basename(snap),
        "pdf": pdf,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)
    rel_out = os.path.relpath(out_dir, root)
    print(f"OK: {rel_out}/{os.path.basename(snap)}"
          + (f" + {pdf}" if pdf else "")
          + f" (validation: {validation}"
          + (", FORCED" if manifest["forced"] else "") + ")")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="submission build: leftover markers are errors")
    ap.add_argument("--force", action="store_true",
                    help="build despite validation errors (recorded)")
    args = ap.parse_args()

    root = repo_root()
    cfg = load_config(root)
    b = cfg.get("workflow", {}).get("build", {})
    main_tex = b.get("main", "main.tex")
    command = b.get("command",
                    "latexmk -pdf -interaction=nonstopmode "
                    "-output-directory={out} {main}")
    broot = os.path.join(root, b.get("dir", "build/"))

    # ---- the gate: no PDF from a dirty manuscript
    validation = "skipped"
    if b.get("validate_first", True):
        ok, out = run_validator(root, args.strict)
        validation = "passed" if ok else "FAILED"
        if not ok and not args.force:
            print(out)
            sys.exit("BUILD REFUSED: the manuscript fails validation "
                     "(above). Fix the errors, or rerun with --force to "
                     "produce a draft PDF anyway (recorded as forced).")
        if not ok:
            print("!! FORCED BUILD despite validation errors:\n" + out)

    version = next_version(broot)
    stamp = datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = os.path.join(broot, f"{stamp}_v{version}")
    os.makedirs(out_dir)

    # ---- docx main: the validated snapshot IS the build artifact.
    # PDF export only if LibreOffice is installed; degrade gracefully.
    if main_tex.lower().endswith(".docx"):
        return build_docx(root, cfg, b, main_tex, out_dir, version, stamp,
                          validation, args)

    cmd = command.format(main=shlex.quote(main_tex),
                         out=shlex.quote(out_dir))
    print(f"build v{version} -> {os.path.relpath(out_dir, root)}")
    print(f"$ {cmd}")
    r = subprocess.run(cmd, shell=True, cwd=root,
                       capture_output=True, text=True, timeout=1800)
    with open(os.path.join(out_dir, "build.log"), "w") as f:
        f.write(r.stdout or "")
        f.write(r.stderr or "")

    pdfs = [f for f in os.listdir(out_dir) if f.endswith(".pdf")]
    manifest = {
        "version": version,
        "timestamp": stamp,
        "git_commit": git_commit(root),
        "main": main_tex,
        "command": cmd,
        "validation": validation,
        "strict": args.strict,
        "forced": args.force and validation == "FAILED",
        "exit_code": r.returncode,
        "pdf": pdfs[0] if pdfs else None,
    }
    with open(os.path.join(out_dir, "manifest.json"), "w") as f:
        json.dump(manifest, f, indent=1)

    if r.returncode != 0 or not pdfs:
        print(f"BUILD FAILED (exit {r.returncode}) — see "
              f"{os.path.relpath(out_dir, root)}/build.log")
        sys.exit(1)
    print(f"OK: {os.path.relpath(os.path.join(out_dir, pdfs[0]), root)} "
          f"(validation: {validation}{', FORCED' if manifest['forced'] else ''})")


if __name__ == "__main__":
    main()
