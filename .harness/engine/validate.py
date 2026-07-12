#!/usr/bin/env python3
"""Paramasastra — generic, config-driven validator.

ALL policy lives in harness.json at the repo root; this engine only
interprets it. Add rules by editing JSON, never this file.

Usage:
    validate.py FILE [FILE ...]      validate specific files
    validate.py --all                validate manuscript+notes+bib
    validate.py --json ...           machine-readable output

Exit codes: 0 = pass (warnings allowed), 1 = ERROR findings exist.
"""
import argparse
import fnmatch
import json
import math
import os
import re
import subprocess
import sys

# ------------------------------------------------------------ config


def has_config(d):
    return (os.path.isdir(os.path.join(d, "harness"))
            or os.path.isfile(os.path.join(d, "harness.json")))


def repo_root():
    env = os.environ.get("CLAUDE_PROJECT_DIR")
    if env and has_config(env):
        return os.path.abspath(env)
    try:
        r = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                           capture_output=True, text=True, timeout=10)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.strip()
    except Exception:
        pass
    # fall back: walk up from this file
    d = os.path.dirname(os.path.abspath(__file__))
    while d != os.path.dirname(d):
        if has_config(d):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


def strip_jsonc(text):
    """Remove // and /* */ comments (string-literal aware)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            while i < n and text[i] != "\n":
                i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            i += 2
            while i + 1 < n and not (text[i] == "*" and text[i + 1] == "/"):
                i += 1
            i += 2; continue
        out.append(c); i += 1
    return "".join(out)


def strip_trailing_commas(text):
    """Remove trailing commas before } or ] — but ONLY outside string
    literals (a naive regex would corrupt regex quantifiers like {2,}
    inside pattern strings)."""
    out, i, n, in_str = [], 0, len(text), False
    while i < n:
        c = text[i]
        if in_str:
            out.append(c)
            if c == "\\" and i + 1 < n:
                out.append(text[i + 1]); i += 2; continue
            if c == '"':
                in_str = False
            i += 1; continue
        if c == '"':
            in_str = True; out.append(c); i += 1; continue
        if c == ",":
            j = i + 1
            while j < n and text[j] in " \t\r\n":
                j += 1
            if j < n and text[j] in "}]":
                i += 1; continue  # drop the trailing comma
        out.append(c); i += 1
    return "".join(out)


def parse_jsonc_file(path):
    with open(path, encoding="utf-8") as f:
        text = strip_jsonc(f.read())
    # tolerate trailing commas (common hand-editing slip)
    text = strip_trailing_commas(text)
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(f"harness config error in {path}: {e}")


def deep_merge(base, frag):
    """Merge frag into base. Dicts merge recursively; lists CONCATENATE
    (deduplicated); scalars: last one wins. To REPLACE a list instead of
    extending it, suffix the key with '=' in the fragment:
        {"protected_branches=": ["trunk"]}
    """
    for k, v in frag.items():
        if k.endswith("="):
            base[k[:-1]] = v
            continue
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        elif isinstance(v, list) and isinstance(base.get(k), list):
            base[k] = base[k] + [x for x in v if x not in base[k]]
        else:
            base[k] = v
    return base


def load_config(root):
    """Composable config: if harness/ exists, merge harness/*.json in
    filename order (use numeric prefixes to control order), then
    harness/rules.d/*.json (each may be a {"custom_rules": [...]} object
    or a bare list of rules). A fragment may declare
    "extends": ["presets/name.json", ...] — those load first.
    Falls back to a single harness.json for minimal projects.
    """
    cdir = os.path.join(root, "harness")
    if not os.path.isdir(cdir):
        return parse_jsonc_file(os.path.join(root, "harness.json"))

    cfg, loaded = {}, set()

    def load_fragment(path):
        rp = os.path.realpath(path)
        if rp in loaded:
            return
        loaded.add(rp)
        frag = parse_jsonc_file(path)
        if isinstance(frag, list):
            frag = {"custom_rules": frag}
        for ext in frag.pop("extends", []):
            load_fragment(os.path.join(cdir, ext))
        deep_merge(cfg, frag)

    for name in sorted(os.listdir(cdir)):
        if name.endswith(".json"):
            load_fragment(os.path.join(cdir, name))
    rd = os.path.join(cdir, "rules.d")
    if os.path.isdir(rd):
        for name in sorted(os.listdir(rd)):
            if name.endswith(".json"):
                load_fragment(os.path.join(rd, name))
    return cfg


# ------------------------------------------------------------ config lint

KNOWN_TOP_KEYS = {"project", "formats", "git", "protected_paths", "prose",
                  "latex_commands", "labels", "scope", "citations",
                  "custom_rules", "enforcement", "workflow",
                  "file_shapes", "latex_floats", "latex_xref",
                  "latex_modularity", "docx"}
SEVERITIES = {"error", "warn", "off"}


def check_config(root, cfg):
    """Lint the effective config: typos, bad regexes, bad severities.
    Returns a list of problem strings."""
    probs = []
    for k in cfg:
        if k not in KNOWN_TOP_KEYS:
            probs.append(f"unknown top-level key '{k}' (typo?) — known: "
                         f"{sorted(KNOWN_TOP_KEYS)}")
    if not cfg.get("project", {}).get("manuscript_paths"):
        probs.append("project.manuscript_paths is empty — the harness "
                     "would govern nothing")
    for field in ("severity_in_manuscript", "severity_in_notes"):
        s = cfg.get("prose", {}).get(field, "error")
        if s not in SEVERITIES:
            probs.append(f"prose.{field}='{s}' not in {sorted(SEVERITIES)}")
    for where, key in (("labels", "severity"), ("scope", "severity")):
        s = cfg.get(where, {}).get(key, "warn")
        if s not in SEVERITIES:
            probs.append(f"{where}.{key}='{s}' not in {sorted(SEVERITIES)}")
    for i, c in enumerate(cfg.get("latex_commands", [])):
        try:
            re.compile(c.get("forbid", ""))
        except re.error as e:
            probs.append(f"latex_commands[{i}].forbid bad regex: {e}")
    for i, p in enumerate(cfg.get("prose", {}).get("banned_patterns", [])):
        pid = p.get("id", f"#{i}")
        try:
            re.compile(p.get("pattern", ""), re.I)
        except re.error as e:
            probs.append(f"prose.banned_patterns[{pid}] bad regex: {e}")
        if p.get("severity", "error") not in SEVERITIES:
            probs.append(f"prose.banned_patterns[{pid}].severity invalid")
    for i, s in enumerate(cfg.get("file_shapes", [])):
        sid = s.get("id", f"#{i}")
        for fam_key in ("allow_only", "require"):
            for p in s.get(fam_key, []):
                try:
                    re.compile(p)
                except re.error as e:
                    probs.append(f"file_shapes[{sid}].{fam_key} bad "
                                 f"regex '{p}': {e}")
        for f in s.get("forbid", []):
            try:
                re.compile(f.get("pattern", ""))
            except re.error as e:
                probs.append(f"file_shapes[{sid}].forbid bad regex: {e}")
        if s.get("severity", "error") not in SEVERITIES:
            probs.append(f"file_shapes[{sid}].severity invalid")
    for key, fields in (("latex_floats", ("severity",)),
                        ("latex_modularity", ("severity",)),
                        ("latex_xref", ("duplicates", "unknown_refs",
                                        "unreferenced_floats"))):
        blk = cfg.get(key, {})
        for f in fields:
            v = blk.get(f, "error")
            if v not in SEVERITIES:
                probs.append(f"{key}.{f}='{v}' not in {sorted(SEVERITIES)}")
    dens = cfg.get("prose", {}).get("density", {})
    if dens:
        mode = dens.get("mode", "rate")
        if mode not in ("rate", "count"):
            probs.append("prose.density.mode must be 'rate' or 'count'")
        if dens.get("under_limit", "off") not in ("off", "warn"):
            probs.append("prose.density.under_limit must be 'off' or 'warn'")
        if dens.get("over_limit", "error") not in SEVERITIES:
            probs.append("prose.density.over_limit invalid severity")
        ma = dens.get("min_allowance", 1)
        if not isinstance(ma, int) or ma < 0:
            probs.append("prose.density.min_allowance must be int >= 0")
        order = ["paragraph", "section", "file", "chapter"]
        for fam in ("per_word", "aggregate"):
            lims = dens.get(fam, {})
            for k, v in lims.items():
                if k not in order:
                    probs.append(f"prose.density.{fam}: unknown scope '{k}'")
                elif not isinstance(v, (int, float)) or v < 0:
                    probs.append(f"prose.density.{fam}.{k} must be a "
                                 "number >= 0")
            vals = [lims[s] for s in order if s in lims]
            if mode == "count" and vals != sorted(vals):
                probs.append(f"WARN: prose.density.{fam} count limits "
                             "should be non-decreasing (paragraph <= "
                             "section <= file <= chapter)")
            if mode == "rate" and vals != sorted(vals, reverse=True):
                probs.append(f"WARN: prose.density.{fam} rates should be "
                             "non-increasing (larger scopes tolerate lower "
                             "per-1000-word rates)")
    for i, r in enumerate(cfg.get("custom_rules", [])):
        rid = r.get("id", f"#{i}")
        if not r.get("pattern"):
            probs.append(f"custom_rules[{rid}]: missing 'pattern'")
        else:
            try:
                re.compile(r["pattern"])
            except re.error as e:
                probs.append(f"custom_rules[{rid}].pattern bad regex: {e}")
        if r.get("severity", "warn") not in SEVERITIES:
            probs.append(f"custom_rules[{rid}].severity invalid")
    for b in cfg.get("citations", {}).get("bib_files", []):
        if not os.path.isfile(os.path.join(root, b)):
            probs.append(f"WARN: citations.bib_files: '{b}' not found (yet?)")
    dx = cfg.get("docx", {})
    if dx:
        dc = dx.get("citations", {})
        for f in ("unmatched_severity", "unparseable_severity"):
            if dc.get(f, "error") not in SEVERITIES:
                probs.append(f"docx.citations.{f}='{dc.get(f)}' not in "
                             f"{sorted(SEVERITIES)}")
        th = dc.get("title_match_threshold", 0.85)
        if not isinstance(th, (int, float)) or not 0 < th <= 1:
            probs.append("docx.citations.title_match_threshold must be a "
                         "number in (0, 1]")
        stx = dx.get("structure", {})
        for f in ("severity", "no_heading_skips"):
            if stx.get(f, "warn") not in SEVERITIES:
                probs.append(f"docx.structure.{f}='{stx.get(f)}' not in "
                             f"{sorted(SEVERITIES)}")
        mh = stx.get("max_h1_per_file", 1)
        if not isinstance(mh, int) or mh < 0:
            probs.append("docx.structure.max_h1_per_file must be int >= 0")
        for p in stx.get("required_headings", []):
            try:
                re.compile(p)
            except re.error as e:
                probs.append(f"docx.structure.required_headings bad regex "
                             f"'{p}': {e}")
        lv = dx.get("density_section_levels", [1, 2])
        if not isinstance(lv, list) or not all(
                isinstance(x, int) and 1 <= x <= 9 for x in lv):
            probs.append("docx.density_section_levels must be a list of "
                         "ints in 1..9")
    return probs


# ------------------------------------------------------------ findings


class Finding:
    def __init__(self, sev, code, path, line, msg):
        self.sev, self.code, self.path, self.line, self.msg = \
            sev.upper(), code, path, line, msg

    def __str__(self):
        loc = f"{self.path}:{self.line}" if self.line else self.path
        return f"[{self.sev}] {self.code} {loc}: {self.msg}"

    def to_dict(self):
        return {"severity": self.sev, "code": self.code, "file": self.path,
                "line": self.line, "message": self.msg}


# ------------------------------------------------------------ helpers

LATEX_EXT = (".tex",)
MD_EXT = (".md", ".qmd", ".rmd", ".Rmd", ".markdown")
DOCX_EXT = (".docx",)
# Plain-text pseudo-citations inside a .docx ([@key] / [12]) — Word
# manuscripts must cite through native Zotero/Word fields instead:
PSEUDO_CITE = re.compile(r"\[@[\w:.#-]+[^\]]*\]|"
                         r"\[\d{1,3}(?:\s*[,;–—-]\s*\d{1,3})*\]")
CITE_LATEX = re.compile(r"\\(?:cite|citep|citet|citealp|citeauthor|citeyear|"
                        r"textcite|parencite|autocite|footcite)\*?"
                        r"(?:\[[^\]]*\])*\{([^}]*)\}")
CITE_MD = re.compile(r"(?<![\w@.])@([A-Za-z][\w:.#-]*[\w])")
BIB_ENTRY = re.compile(r"^\s*@(\w+)\s*\{\s*([^,\s]+)\s*,", re.M)


def norm(p):
    return p.replace(os.sep, "/")


def relpath(root, path):
    try:
        return norm(os.path.relpath(os.path.abspath(path), root))
    except ValueError:
        return norm(path)


def path_in(rel, prefixes):
    return any(rel.startswith(norm(p).rstrip("/") + "/") or rel == norm(p).rstrip("/")
               for p in prefixes)


def classify(rel, cfg):
    proj = cfg.get("project", {})
    if path_in(rel, proj.get("manuscript_paths", [])):
        return "manuscript"
    if path_in(rel, proj.get("notes_paths", [])):
        return "notes"
    return None


def eff_severity(base, zone, cfg):
    """Resolve severity: notes zone downgrades errors to the configured level."""
    if base == "off":
        return None
    if zone == "notes":
        notes_sev = cfg.get("prose", {}).get("severity_in_notes", "warn")
        return notes_sev if base == "error" else base
    return base


def strip_latex_comment(line):
    out, prev = [], ""
    for ch in line:
        if ch == "%" and prev != "\\":
            break
        out.append(ch); prev = ch
    return "".join(out)


def iter_prose_lines(text, kind):
    """Yield (lineno, prose_line, raw_line). prose_line has comments
    removed (may be empty for comment-only lines — workflow markers live
    in comments, so raw_line is needed to see them)."""
    fenced = verb = False
    for n, raw in enumerate(text.splitlines(), 1):
        if kind == "md":
            if raw.lstrip().startswith("```"):
                fenced = not fenced
                continue
            if fenced:
                continue
            yield n, raw, raw
        else:
            if re.search(r"\\begin\{(lstlisting|verbatim|minted)", raw):
                verb = True
            if re.search(r"\\end\{(lstlisting|verbatim|minted)", raw):
                verb = False
                continue
            if verb:
                continue
            yield n, strip_latex_comment(raw), raw


def prose_units(text, kind, cfg, doc=None):
    """Unified per-format prose stream: (lineno, prose, raw, meta).
    tex/md wrap iter_prose_lines; docx delegates to ooxml (the paragraph
    is the 'line', see ooxml.py). meta: blank, heading (density section
    boundary), and for docx the paragraph's citation fields."""
    if kind == "docx":
        import ooxml
        yield from ooxml.iter_prose_units(doc, cfg)
        return
    for n, line, raw in iter_prose_lines(text, kind):
        blank = not line.strip()
        heading = bool(not blank and (
            re.search(r"\\(chapter|section)\s*[*{]", line) if kind == "tex"
            else re.match(r"#{1,2}\s", line)))
        yield n, line, raw, {"blank": blank, "heading": heading}


# ------------------------------------------------------------ bib


def parse_bibs(root, cfg):
    """Return (keys:set, entries:list of dict(type,key,fields,file,line))."""
    keys, entries = set(), []
    for b in cfg.get("citations", {}).get("bib_files", []):
        fp = os.path.join(root, b)
        if not os.path.isfile(fp):
            continue
        text = open(fp, encoding="utf-8", errors="replace").read()
        for m in BIB_ENTRY.finditer(text):
            etype, key = m.group(1).lower(), m.group(2)
            if etype in ("comment", "string", "preamble"):
                continue
            # crude field scan until next @entry
            nxt = BIB_ENTRY.search(text, m.end())
            body = text[m.end(): nxt.start() if nxt else len(text)]
            fields = {fm.group(1).lower(): fm.group(2).strip()
                      for fm in re.finditer(
                          r"(\w+)\s*=\s*[{\"']?([^,\n}]*)", body)}
            keys.add(key)
            entries.append({"type": etype, "key": key, "fields": fields,
                            "file": relpath(root, fp),
                            "line": text[:m.start()].count("\n") + 1})
    return keys, entries


def check_local_sources(root, entries, cfg, findings):
    """References-first shelf policy: every bib entry must carry a
    file = {<shelf>/<name>.pdf} field pointing to a source file the user
    physically placed on the shelf. A reference that was only suggested
    (never downloaded) cannot enter the bibliography."""
    ls = cfg.get("citations", {}).get("local_sources", {})
    if not ls.get("enabled", False):
        return
    sev = ls.get("severity", "error")
    shelf = norm(ls.get("dir", "references/")).rstrip("/") + "/"
    for e in entries:
        fpath = e["fields"].get("file", "").strip().strip("{}").strip()
        if not fpath:
            findings.append(Finding(
                sev, "E-BIBSRC", e["file"], e["line"],
                f"{e['key']}: no file field — every entry must point at "
                f"its source on the shelf (file = {{{shelf}<name>.pdf}}). "
                "If this source is not downloaded yet, it cannot be "
                "cited: suggest it to the user instead"))
            continue
        want = ls.get("type_dirs", {}).get(e["type"])
        if want and not norm(fpath).startswith(norm(want)):
            findings.append(Finding(
                sev, "E-BIBSRC", e["file"], e["line"],
                f"{e['key']}: @{e['type']} sources belong in '{want}' — "
                f"file field points to '{fpath}'"))
        elif not norm(fpath).startswith(shelf):
            findings.append(Finding(
                sev, "E-BIBSRC", e["file"], e["line"],
                f"{e['key']}: file field '{fpath}' is outside the shelf "
                f"directory '{shelf}'"))
        elif not os.path.isfile(os.path.join(root, fpath)):
            findings.append(Finding(
                sev, "E-BIBSRC", e["file"], e["line"],
                f"{e['key']}: file field points to '{fpath}' which does "
                "not exist — the user has not placed this source on the "
                "shelf; it cannot be cited yet"))


def check_bib_entries(entries, cfg, findings):
    cit = cfg.get("citations", {})
    allowed = [t.lower() for t in cit.get("allowed_types", [])]
    exceptions = cit.get("type_exceptions", [])
    reqf = {k.lower(): v for k, v in cit.get("required_fields", {}).items()}
    for e in entries:
        if allowed and e["type"] not in allowed:
            ok = any(e["type"] == x.get("type", "").lower()
                     and e["key"].lower().startswith(x.get("key_prefix", "").lower())
                     for x in exceptions)
            if not ok:
                findings.append(Finding(
                    "error", "E-BIBTYPE", e["file"], e["line"],
                    f"@{e['type']}{{{e['key']}}} not in allowed_types {allowed}"))
        for f in reqf.get(e["type"], []):
            if not e["fields"].get(f):
                findings.append(Finding(
                    "error", "E-BIBFIELD", e["file"], e["line"],
                    f"{e['key']}: required field '{f}' missing/empty "
                    f"(anti-fabrication anchor for @{e['type']})"))


# ------------------------------------------------------------ file checks


WORD_RE = re.compile(r"[A-Za-z']+")
LABEL_RE = re.compile(r"\\label\{([^}]+)\}")
REF_RE = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref|vref)\{([^}]+)\}")
FLOAT_BEGIN = re.compile(r"\\begin\{(figure|table)\*?\}")
FLOAT_END = re.compile(r"\\end\{(figure|table)\*?\}")


def check_file_shapes(rel, text, cfg, findings):
    """Whole-file structural contracts (e.g. 'a chapter root file holds
    only \\chapter and \\input lines'). Declared in config as
    file_shapes: [{id, glob, allow_only, require, forbid, severity}]."""
    for shape in cfg.get("file_shapes", []):
        if not fnmatch.fnmatch(rel, shape.get("glob", "*")):
            continue
        sev = shape.get("severity", "error")
        sid = shape.get("id", "F-SHAPE")
        allow = [re.compile(p) for p in shape.get("allow_only", [])]
        forbid = shape.get("forbid", [])
        required = {p: re.compile(p) for p in shape.get("require", [])}
        found_req = set()
        for n, raw in enumerate(text.splitlines(), 1):
            line = strip_latex_comment(raw).strip()
            if not line:
                continue
            for p, reg in required.items():
                if reg.search(line):
                    found_req.add(p)
            for f in forbid:
                if re.search(f.get("pattern", "(?!)"), line):
                    findings.append(Finding(
                        sev, sid, rel, n,
                        f.get("message", "forbidden in this file shape")))
            if allow and not any(a.search(line) for a in allow):
                findings.append(Finding(
                    sev, sid, rel, n,
                    shape.get("message",
                              "line not permitted by this file's shape "
                              "contract") + f" (line: '{line[:60]}')"))
        for p in required:
            if p not in found_req:
                findings.append(Finding(
                    sev, sid, rel, 0,
                    f"required pattern '{p}' missing from this file"))


ROOT_ALLOWED = re.compile(
    r"^\s*\\(chapter|input|include|label|usetikzlibrary|graphicspath|"
    r"clearpage|newpage|cleardoublepage)\b")


def check_modularity(rel, text, cfg, findings):
    """Glob-free modular-writing contract (works whatever path the AI
    invents for a file):
      1. A file containing \\chapter is a chapter ROOT: it may hold only
         structural commands (\\chapter, \\input, \\label, ...) — no
         \\section, no prose.
      2. No file may contain 2+ \\section commands — that is a monolith;
         each section lives in its own sub-file, pulled in by \\input.
    """
    mod = cfg.get("latex_modularity", {})
    if not mod.get("enabled", False):
        return
    sev = mod.get("severity", "error")
    max_sec = int(mod.get("max_sections_per_file", 1))
    has_chapter = False
    section_lines = []
    prose_lines = []
    for n, raw in enumerate(text.splitlines(), 1):
        line = strip_latex_comment(raw)
        if not line.strip():
            continue
        if re.search(r"\\chapter\*?\{", line):
            has_chapter = True
        if re.search(r"\\section\*?\{", line):
            section_lines.append(n)
        if has_chapter and not ROOT_ALLOWED.match(line):
            prose_lines.append(n)
    if has_chapter and mod.get("chapter_root_only", True):
        if section_lines:
            findings.append(Finding(
                sev, "L-MODULAR", rel, section_lines[0],
                "file contains \\chapter AND \\section — a chapter file is "
                "a ROOT holding only \\chapter and \\input{} calls; each "
                "section goes in its own sub-file (e.g. "
                "ch2/sec-related-work.tex) pulled in with \\input"))
        if prose_lines:
            findings.append(Finding(
                sev, "L-MODULAR", rel, prose_lines[0],
                f"prose/content in a chapter root file ({len(prose_lines)} "
                "line(s)) — move it into \\input'd sub-files; the root "
                "holds structure only"))
    elif len(section_lines) > max_sec:
        findings.append(Finding(
            sev, "L-MODULAR", rel, section_lines[max_sec],
            f"{len(section_lines)} \\section commands in one file "
            f"(max {max_sec}) — monolithic chapter writing; split into "
            "one sub-file per section (sec-<slug>.tex) with a root file "
            "of \\input calls"))
    elif section_lines and mod.get("section_in_own_dir", False):
        # section-as-directory: sec-<slug>/sec-<slug>.tex, assets beside it
        stem = os.path.splitext(os.path.basename(rel))[0]
        parent = os.path.basename(os.path.dirname(rel))
        if parent != stem:
            findings.append(Finding(
                sev, "L-MODULAR", rel, section_lines[0],
                f"section file '{stem}.tex' must live in its own "
                f"directory: .../{stem}/{stem}.tex (assets — figures, "
                "listings, images — co-locate inside that folder)"))


GRAPHIC_EXTS = ("", ".pdf", ".png", ".jpg", ".jpeg", ".eps", ".svg")


def check_graphic(rel, target, n, fl, findings):
    """\\includegraphics target must exist (an image the user never
    added cannot be included — same shelf philosophy as citations), and
    should live beside the section that uses it (co-location)."""
    root = repo_root()
    exist_sev = fl.get("graphics_exist", "error")
    if exist_sev == "off":
        return
    tex_dir = os.path.dirname(rel)
    bases = [".", tex_dir] + fl.get("graphics_paths", [])
    resolved = None
    for b in bases:
        for ext in GRAPHIC_EXTS:
            cand = os.path.normpath(os.path.join(root, b, target + ext))
            if os.path.isfile(cand):
                resolved = os.path.relpath(cand, root)
                break
        if resolved:
            break
    if not resolved:
        findings.append(Finding(
            exist_sev, "L-GRAPHIC", rel, n,
            f"\\includegraphics{{{target}}}: image file not found (tried "
            f"relative to repo root, '{tex_dir}/', and graphics_paths) — "
            "ask the user to add the image beside its section; do not "
            "reference images that do not exist"))
        return
    co_sev = fl.get("graphics_colocate", "warn")
    if co_sev != "off" and tex_dir and \
            not norm(resolved).startswith(norm(tex_dir) + "/"):
        findings.append(Finding(
            co_sev, "L-GRAPHIC", rel, n,
            f"image '{resolved}' lives outside this section's directory "
            f"'{tex_dir}/' — co-locate assets with the section that "
            "discusses them"))


def check_latex_structure(rel, text, cfg, findings, xref_acc):
    """Float integrity (caption+label per figure/table env, no stray
    \\includegraphics) and label/ref collection for corpus-level
    cross-reference checks."""
    fl = cfg.get("latex_floats", {})
    sev = fl.get("severity", "error")
    in_float = None      # (env, start_line, has_caption, has_label, labels)
    labels_here = {}     # name -> first line
    xr = cfg.get("latex_xref", {})
    for n, raw in enumerate(text.splitlines(), 1):
        line = strip_latex_comment(raw)
        m = FLOAT_BEGIN.search(line)
        if m and fl.get("enabled", True):
            in_float = [m.group(1), n, False, False]
        if in_float:
            if r"\caption" in line:
                in_float[2] = True
            if r"\label" in line:
                in_float[3] = True
        e = FLOAT_END.search(line)
        if e and in_float and fl.get("enabled", True):
            env, start, has_cap, has_lab = in_float
            if fl.get("require_caption", True) and not has_cap:
                findings.append(Finding(sev, "L-FLOAT", rel, start,
                                        f"{env} environment has no \\caption"))
            if fl.get("require_label", True) and not has_lab:
                findings.append(Finding(sev, "L-FLOAT", rel, start,
                                        f"{env} environment has no \\label"))
            in_float = None
        if fl.get("enabled", True) and fl.get("graphics_in_float", True) \
                and r"\includegraphics" in line and not in_float:
            findings.append(Finding(
                sev, "L-FLOAT", rel, n,
                "\\includegraphics outside a figure/table environment — "
                "wrap it in a float with \\caption and \\label"))
        if fl.get("enabled", True):
            for gm in re.finditer(
                    r"\\includegraphics(?:\[[^\]]*\])?\{([^}]+)\}", line):
                check_graphic(rel, gm.group(1), n, fl, findings)
        for lm in LABEL_RE.finditer(line):
            name = lm.group(1)
            if name in labels_here:
                if xr.get("duplicates", "error") != "off":
                    findings.append(Finding(
                        xr.get("duplicates", "error"), "L-XREF", rel, n,
                        f"duplicate \\label{{{name}}} (first at line "
                        f"{labels_here[name]})"))
            else:
                labels_here[name] = n
            xref_acc["labels"].setdefault(name, []).append((rel, n))
        for rm in REF_RE.finditer(line):
            xref_acc["refs"].setdefault(rm.group(1), (rel, n))
    xref_acc["files"] += 1


def finalize_xref(cfg, xref_acc, findings):
    """Corpus-level cross-reference checks — only meaningful when 2+
    files were scanned together (--all, pre-commit, CI, stop gate);
    a single file legitimately refs labels defined elsewhere."""
    xr = cfg.get("latex_xref", {})
    if xref_acc["files"] < 2:
        return
    dup_sev = xr.get("duplicates", "error")
    if dup_sev != "off":
        for name, sites in sorted(xref_acc["labels"].items()):
            files = {s[0] for s in sites}
            if len(files) > 1:
                findings.append(Finding(
                    dup_sev, "L-XREF", sites[1][0], sites[1][1],
                    f"\\label{{{name}}} defined in multiple files: "
                    f"{sorted(files)}"))
    unk = xr.get("unknown_refs", "error")
    if unk != "off":
        for name, (f, n) in sorted(xref_acc["refs"].items()):
            if name not in xref_acc["labels"]:
                findings.append(Finding(
                    unk, "L-XREF", f, n,
                    f"\\ref{{{name}}} has no matching \\label in the "
                    "scanned files"))
    unrf = xr.get("unreferenced_floats", "error")
    prefixes = tuple(xr.get("float_prefixes", ["fig:", "tab:", "lst:"]))
    if unrf != "off":
        for name, sites in sorted(xref_acc["labels"].items()):
            if name.startswith(prefixes) and name not in xref_acc["refs"]:
                findings.append(Finding(
                    unrf, "L-XREF", sites[0][0], sites[0][1],
                    f"float \\label{{{name}}} is never referenced in the "
                    "text — every figure/table must be discussed"))


def inflections(w):
    """Deterministic inflection variants of a base word (naive English
    morphology — no dictionary, same output every run)."""
    v = {w}
    if w.endswith("y") and len(w) > 3:
        v |= {w[:-1] + "ies", w[:-1] + "ied"}
    elif w.endswith("e"):
        v |= {w + "s", w + "d", w[:-1] + "ing"}
    elif not w.endswith("s"):
        v |= {w + "s", w + "es", w + "ed", w + "ing"}
    return v


def build_suspect_matchers(suspects, families=True):
    """Return [(lemma, compiled_regex)]. With families=True each entry
    matches its inflection variants ('highlight' also catches
    'highlights'/'highlighting'), and configured entries that are
    themselves variants of an earlier entry are folded into it so one
    occurrence never counts twice. Multi-word entries inflect their
    first token ('align with' also catches 'aligns with')."""
    matchers, seen_variants = [], set()
    for w in suspects:
        if not families:
            matchers.append((w, re.compile(rf"\b{re.escape(w)}\b")))
            continue
        if w in seen_variants:
            continue  # variant of an earlier lemma
        parts = w.split()
        var = sorted(inflections(parts[0]), key=len, reverse=True)
        seen_variants |= ({" ".join([x] + parts[1:]) for x in var}
                          if len(parts) > 1 else set(var))
        alt = "|".join(re.escape(x) for x in var)
        tail = "".join(r"\s+" + re.escape(p) for p in parts[1:])
        matchers.append((w, re.compile(rf"\b(?:{alt}){tail}\b")))
    return matchers


def density_allowance(dens, family, kind, words):
    """Effective limit for a scope. mode='count': the configured number.
    mode='rate' (default): configured value is per 1000 words —
    allowance = max(min_allowance, ceil(rate * words / 1000))."""
    lim = dens.get(family, {}).get(kind)
    if lim is None:
        return None
    if dens.get("mode", "rate") == "count":
        return int(lim)
    return max(int(dens.get("min_allowance", 1)),
               math.ceil(lim * words / 1000.0 - 1e-9))


def eval_density(rel, hits, scope_words, file_word_total, dens, zone, cfg,
                 findings):
    """Deferred density evaluation, run after the file scan."""
    over = dens.get("over_limit", "error")
    sevd = eff_severity(over, zone, cfg)
    if not hits or not sevd:
        return
    # Containment rule: an outer scope only evaluates hit sets that SPAN
    # multiple inner scopes. Its job is catching spread-out clustering the
    # inner scope cannot see — never re-judging (with its stricter rate)
    # hits that a single inner scope already permitted. The chapter scope
    # applies the same rule via its 2-files minimum.
    scopes = [("paragraph", 1, None), ("section", 2, 1), ("file", None, 2)]
    for kind, key_idx, inner_idx in scopes:
        groups = {}
        for h in hits:
            idx = 0 if key_idx is None else h[key_idx]
            groups.setdefault(idx, []).append(h)
        for idx, ghits in groups.items():
            words = (file_word_total if kind == "file"
                     else scope_words[kind].get(idx, 0))
            lim = density_allowance(dens, "per_word", kind, words)
            if lim is not None:
                per = {}
                for h in ghits:
                    per.setdefault(h[0], []).append(h)
                for lemma, lhits in per.items():
                    if inner_idx is not None and \
                            len({h[inner_idx] for h in lhits}) < 2:
                        continue  # all inside one inner scope
                    if len(lhits) > lim:
                        findings.append(Finding(
                            sevd, "P-DENSITY", rel, lhits[lim][3],
                            f"suspect word '{lemma}' appears {len(lhits)}x "
                            f"in this {kind} of {words} words (allowed "
                            f"{lim}) — clustering is a machine tell; vary "
                            "the wording or cut"))
            alim = density_allowance(dens, "aggregate", kind, words)
            if alim is not None and len(ghits) > alim:
                if inner_idx is not None and \
                        len({h[inner_idx] for h in ghits}) < 2:
                    continue
                findings.append(Finding(
                    sevd, "P-DENSITY", rel, ghits[alim][3],
                    f"{len(ghits)} suspect-word occurrences in this {kind} "
                    f"of {words} words (allowed {alim}) — the vocabulary "
                    "profile reads machine-generated; use plainer words"))


def marker_patterns(cfg):
    """Compile workflow marker tokens into matchers."""
    mk = cfg.get("workflow", {}).get("markers", {})
    if not mk:
        return None

    def tmpl(key):
        t = mk.get(key)
        if not t:
            return None
        return re.compile(re.escape(t).replace(r"\{id\}", r"([\w-]+)"))

    return {
        "todo": mk.get("todo"),
        "cite": mk.get("cite"),
        "edit": mk.get("edit"),
        "edit_re": re.compile(re.escape(mk["edit"]) + r"\[([\w-]+)\|(\w+)")
                   if mk.get("edit") else None,
        "ob": tmpl("original_begin"), "oe": tmpl("original_end"),
        "db": tmpl("delete_begin"), "de": tmpl("delete_end"),
    }


def check_markers_post(rel, state, sev, findings):
    """After the line scan: enforce the handoff contract (pair integrity)."""
    for rid, line in state["rewrites"]:
        if rid not in state["original_ids"]:
            findings.append(Finding(
                "error", "E-MARKER", rel, line,
                f"REWRITE marker '{rid}' has no matching ORIGINAL block — "
                "re-run the revise skill to place it"))
    for kind_, opens in (("ORIGINAL", state["open_orig"]),
                         ("DELETE", state["open_del"])):
        for rid, line in opens.items():
            findings.append(Finding(
                "error", "E-MARKER", rel, line,
                f"{kind_} block '{rid}' opened but never closed"))


def check_prose_file(root, rel, text, kind, zone, cfg, findings, bib_keys,
                     doc=None):
    prose = cfg.get("prose", {})
    base = prose.get("severity_in_manuscript", "error")
    words = [w.lower() for w in
             prose.get("forbidden_words", []) + prose.get("extra_words", [])]
    phrases = [p.lower() for p in prose.get("banned_phrases", [])]
    # Suspect words: legitimate in isolation, a machine tell when they
    # CLUSTER. Enforcement is density-based and deterministic. In "rate"
    # mode, limits are expressed per 1000 words of the scope and the
    # effective allowance is computed from the scope's actual length —
    # evaluation is therefore deferred to the end of the scan, when the
    # scope word counts are known.
    suspects = [w.lower() for w in prose.get("suspect_words", [])]
    dens = prose.get("density", {})
    matchers = build_suspect_matchers(
        suspects, dens.get("families", True))
    under = dens.get("under_limit", "off")
    para_i = sec_i = 0
    prev_blank = True
    hits = []          # (lemma, para_i, sec_i, line)
    scope_words = {"paragraph": {}, "section": {}}
    file_word_total = 0
    # Banned constructions (regex): negative parallelism, weasel
    # attribution, copula swaps, trailing -ing analysis clauses, ...
    patterns = []
    for p in prose.get("banned_patterns", []):
        try:
            patterns.append((re.compile(p.get("pattern", "(?!)"), re.I), p))
        except re.error:
            pass  # reported by --check-config
    scope = cfg.get("scope", {})
    scope_kw = [k.lower() for k in scope.get("deny_keywords", [])]
    labels = cfg.get("labels", {})
    cmds = cfg.get("latex_commands", [])
    cust = [r for r in cfg.get("custom_rules", [])
            if fnmatch.fnmatch(rel, r.get("glob", "*"))]
    cite_check = cfg.get("citations", {}).get("cite_keys_must_exist", False)

    # Workflow markers (scaffold/draft/revise handoff contract)
    mp = marker_patterns(cfg)
    wf = cfg.get("workflow", {})
    msev = "error" if cfg.get("_strict_markers") else \
        wf.get("marker_severity", "warn")
    state = {"rewrites": [], "original_ids": set(),
             "open_orig": {}, "open_del": {}}
    in_block = False

    for n, line, raw, meta in prose_units(text, kind, cfg, doc=doc):
        # Scope tracking (density): paragraph and section boundaries
        if meta.get("blank"):
            if not prev_blank:
                para_i += 1
            prev_blank = True
        else:
            prev_blank = False
            if meta.get("heading"):
                sec_i += 1
                para_i += 1

        if mp:
            hit = None
            for pat, reg, opens in (("oe", mp["oe"], None),
                                    ("de", mp["de"], None)):
                m = reg.search(raw) if reg else None
                if m:
                    src = state["open_orig"] if pat == "oe" else state["open_del"]
                    src.pop(m.group(1), None)
                    in_block = False
                    hit = f"block end '{m.group(1)}'"
                    break
            if not hit and not in_block:
                for pat, reg in (("ob", mp["ob"]), ("db", mp["db"])):
                    m = reg.search(raw) if reg else None
                    if m:
                        dst = state["open_orig"] if pat == "ob" else state["open_del"]
                        dst[m.group(1)] = n
                        if pat == "ob":
                            state["original_ids"].add(m.group(1))
                        in_block = True
                        hit = f"block start '{m.group(1)}'"
                        break
            if not hit and in_block:
                continue  # content awaiting rewrite/deletion: not prose
            if not hit:
                m = mp["edit_re"].search(raw) if mp["edit_re"] else None
                if m:
                    if m.group(2).upper() == "REWRITE":
                        state["rewrites"].append((m.group(1), n))
                    hit = f"edit marker '{m.group(1)}|{m.group(2)}'"
                elif any(t and t in raw for t in
                         (mp["todo"], mp["cite"], mp["edit"])):
                    hit = "todo/cite marker"
            if hit:
                if msev != "off":
                    findings.append(Finding(
                        msev, "W-MARKER", rel, n,
                        f"workflow {hit} — must be resolved before delivery"))
                continue  # marker lines are instructions, not prose

        if not line.strip():
            continue
        lower = line.lower()

        # Scope word counts (density-rate denominators)
        wc_line = len(WORD_RE.findall(line))
        scope_words["paragraph"][para_i] = \
            scope_words["paragraph"].get(para_i, 0) + wc_line
        scope_words["section"][sec_i] = \
            scope_words["section"].get(sec_i, 0) + wc_line
        file_word_total += wc_line

        sev = eff_severity(base, zone, cfg) if prose.get("forbid_em_dash", True) else None
        if sev and "—" in line:
            findings.append(Finding(sev, "P-EMDASH", rel, n,
                                    "em-dash prohibited in prose; rewrite with "
                                    "comma, colon, parentheses, or two sentences"))

        sev = eff_severity(base, zone, cfg)
        if sev:
            for w in words:
                if re.search(rf"\b{re.escape(w)}\b", lower):
                    findings.append(Finding(sev, "P-VOCAB", rel, n,
                                            f"forbidden vocabulary '{w}'"))
            for ph in phrases:
                if ph in lower:
                    findings.append(Finding(sev, "P-PHRASE", rel, n,
                                            f"banned phrase '{ph}'"))
            for creg, p in patterns:
                if creg.search(line):
                    psev = eff_severity(p.get("severity", "error"), zone, cfg)
                    if psev:
                        findings.append(Finding(
                            psev, p.get("id", "P-PATTERN"), rel, n,
                            p.get("message", "banned construction")))

        for lemma, rx in matchers:
            for _ in rx.finditer(lower):
                hits.append((lemma, para_i, sec_i, n))
                if under == "warn":
                    findings.append(Finding(
                        "warn", "P-SUSPECT", rel, n,
                        f"suspect word '{lemma}' — fine in isolation, a "
                        "tell when it clusters"))

        ssev = eff_severity(scope.get("severity", "warn"), zone, cfg)
        if ssev:
            for k in scope_kw:
                if re.search(rf"\b{re.escape(k)}\b", lower):
                    findings.append(Finding(
                        ssev, "S-SCOPE", rel, n,
                        f"out-of-scope keyword '{k}' — check the scope "
                        "statement in harness.json before writing about this"))

        if kind == "tex":
            for c in cmds:
                if re.search(c.get("forbid", "(?!)"), line):
                    findings.append(Finding(
                        eff_severity("error", zone, cfg) or "warn",
                        "L-CMD", rel, n,
                        f"use {c.get('use', '?')} instead of the raw command"))
            lsev = labels.get("severity", "warn")
            prefixes = tuple(labels.get("prefixes", []))
            if lsev != "off" and prefixes:
                for m in re.finditer(r"\\label\{([^}]*)\}", line):
                    if not m.group(1).startswith(prefixes):
                        findings.append(Finding(
                            lsev, "L-LABEL", rel, n,
                            f"label '{m.group(1)}' lacks a convention prefix "
                            f"{prefixes}"))

        for r in cust:
            if re.search(r.get("pattern", "(?!)"), line):
                findings.append(Finding(
                    r.get("severity", "warn"),
                    r.get("id", "C-CUSTOM"), rel, n,
                    r.get("message", "custom rule matched")))

        if kind == "docx" and cfg.get("docx", {}).get("citations", {}).get(
                "require_native_fields", True):
            m = PSEUDO_CITE.search(line)
            if m:
                findings.append(Finding(
                    "warn", "O-CITE", rel, n,
                    f"plain-text citation '{m.group(0)}' — Word manuscripts "
                    "cite through native Zotero/Word citation fields, not "
                    "typed brackets (docxtool.py add-cite, or insert via "
                    "Zotero and let the field resolve)"))

        if cite_check and bib_keys is not None and kind != "docx":
            used = []
            if kind == "tex":
                for m in CITE_LATEX.finditer(line):
                    used += [k.strip() for k in m.group(1).split(",") if k.strip()]
            else:
                used += CITE_MD.findall(line)
            for k in used:
                if k not in bib_keys:
                    findings.append(Finding(
                        eff_severity("error", zone, cfg) or "warn",
                        "C-KEY", rel, n,
                        f"cite key '{k}' not found in any configured bib "
                        "file — possible hallucinated citation"))

        # Bare TODO markers: always warn (drafting is legitimate)
        if re.search(r"\\todo\b|\bTODO\b|\bFIXME\b", line):
            findings.append(Finding("warn", "P-TODO", rel, n,
                                    "TODO marker — remove before submission"))

    check_markers_post(rel, state, msev, findings)
    eval_density(rel, hits, scope_words, file_word_total, dens, zone, cfg,
                 findings)
    fw = {}
    for h in hits:
        fw[h[0]] = fw.get(h[0], 0) + 1
    return {"words": fw, "total_words": file_word_total}


def check_docx_structure(rel, doc, cfg, findings):
    """O-STRUCT — heading contracts, the docx analog of file_shapes /
    L-MODULAR: one top-level heading per file, no skipped levels,
    optional required headings. Levels come from w:outlineLvl (resolved
    through style basedOn chains), never localized style names."""
    st = cfg.get("docx", {}).get("structure", {})
    if not st.get("enabled", True):
        return
    sev = st.get("severity", "error")
    headings = [(p.index, p.outline_level, p.text)
                for p in doc.paras if p.outline_level]
    max_h1 = int(st.get("max_h1_per_file", 1))
    h1s = [h for h in headings if h[1] == 1]
    if sev != "off" and len(h1s) > max_h1:
        findings.append(Finding(
            sev, "O-STRUCT", rel, h1s[max_h1][0],
            f"{len(h1s)} top-level headings in one document (max {max_h1}) "
            "— one chapter/document per file; split further content into "
            "its own .docx"))
    skip_sev = st.get("no_heading_skips", "warn")
    if skip_sev != "off":
        prev = 0
        for idx, lvl, txt in headings:
            if prev and lvl > prev + 1:
                findings.append(Finding(
                    skip_sev, "O-STRUCT", rel, idx,
                    f"heading level jumps H{prev} -> H{lvl} "
                    f"('{txt[:40]}') — do not skip heading levels"))
            prev = lvl
    if sev != "off":
        for pat in st.get("required_headings", []):
            try:
                reg = re.compile(pat)
            except re.error:
                continue  # reported by --check-config
            if not any(reg.search(t) for _, _, t in headings):
                findings.append(Finding(
                    sev, "O-STRUCT", rel, 0,
                    f"required heading matching '{pat}' is missing"))


def check_docx_citations(rel, doc, cfg, findings, entries):
    """O-FIELD / O-CITE — every native citation field must parse and
    resolve to exactly one references.bib entry (DOI, then ISBN, then
    fuzzy title). This keeps the anti-fabrication chain intact: bib
    entry => required identifiers => shelf file => online verification.
    A DOI that exists only inside a Word field is a violation, not
    something to verify ad hoc."""
    import ooxml
    dc = cfg.get("docx", {}).get("citations", {})
    sev_un = dc.get("unmatched_severity", "error")
    sev_bad = dc.get("unparseable_severity", "error")
    th = float(dc.get("title_match_threshold", 0.85))
    sources = doc.sources()
    for fld in doc.fields:
        if fld.kind == "other":
            continue
        where = " (in a footnote)" if fld.location == "footnote" else ""
        if fld.broken:
            if sev_bad != "off":
                findings.append(Finding(
                    sev_bad, "O-FIELD", rel, fld.para_index,
                    f"broken citation field{where}: "
                    f"{fld.reason or 'field structure damaged'} — repair it "
                    "in Word/Zotero (or delete and re-insert the citation)"))
            continue
        items = fld.items
        if fld.kind == "word":
            src = sources.get(fld.tag)
            if src is None:
                if sev_bad != "off":
                    findings.append(Finding(
                        sev_bad, "O-FIELD", rel, fld.para_index,
                        f"CITATION field references source tag "
                        f"'{fld.tag}' which is not in the document's "
                        "bibliography sources"))
                continue
            items = [src]
        if entries is None or sev_un == "off":
            continue
        for item in items:
            key, _how = ooxml.match_bib(item, entries, th)
            if key is None:
                ident = (item.get("doi") or item.get("isbn")
                         or (item.get("title") or "")[:60] or "?")
                findings.append(Finding(
                    sev_un, "O-CITE", rel, fld.para_index,
                    f"citation field ({ident}){where} matches no entry in "
                    "the configured bib file(s) — every cited work must be "
                    "on the shelf and in the bib first; possible fabricated "
                    "citation"))
            else:
                fld.matched = key


def check_protected(root, rel, cfg, findings):
    pp = cfg.get("protected_paths", {})
    if os.environ.get(pp.get("override_env", "ALLOW_PROTECTED")) == "1":
        return False
    for d in pp.get("deny", []):
        if rel.startswith(norm(d)):
            findings.append(Finding(
                "error", "X-PROTECTED", rel, 0,
                f"'{d}' is protected — must not be modified "
                f"(override: {pp.get('override_env', 'ALLOW_PROTECTED')}=1 "
                "when explicitly requested)"))
            return True
    return False


def check_file(root, path, cfg, findings, bib_keys, chapter_acc=None,
               xref_acc=None, bib_entries=None):
    rel = relpath(root, path)
    if check_protected(root, rel, cfg, findings):
        return
    if not os.path.isfile(path):
        return
    fmts = cfg.get("formats", {})
    if rel.endswith(".bib"):
        return  # bib files validated once, globally
    kind = None
    if fmts.get("latex", True) and rel.endswith(LATEX_EXT):
        kind = "tex"
    elif fmts.get("markdown", False) and rel.lower().endswith(
            tuple(e.lower() for e in MD_EXT)):
        kind = "md"
    elif fmts.get("docx", False) and rel.lower().endswith(DOCX_EXT):
        kind = "docx"
    if not kind:
        return
    zone = classify(rel, cfg)
    if zone is None:
        return  # outside manuscript/notes => not prose
    text = doc = None
    if kind == "docx":
        if os.path.basename(rel).startswith("~$"):
            return  # Word owner-lock temp file, not a manuscript
        import ooxml
        try:
            doc = ooxml.load(path)
        except ooxml.DocxError as e:
            findings.append(Finding("error", "O-FIELD", rel, 0,
                                    f"cannot parse .docx: {e}"))
            return
        check_docx_structure(rel, doc, cfg, findings)
        check_docx_citations(rel, doc, cfg, findings, bib_entries)
    else:
        text = open(path, encoding="utf-8", errors="replace").read()
        check_file_shapes(rel.replace(os.sep, "/"), text, cfg, findings)
        if kind == "tex":
            check_modularity(rel, text, cfg, findings)
            if xref_acc is not None:
                check_latex_structure(rel, text, cfg, findings, xref_acc)
    fw = check_prose_file(root, rel, text, kind, zone, cfg, findings,
                          bib_keys, doc=doc)
    if chapter_acc is not None and zone == "manuscript" and fw is not None:
        d = os.path.dirname(rel.replace(os.sep, "/"))
        ch = chapter_acc.setdefault(
            d, {"files": 0, "words": {}, "total_words": 0})
        ch["files"] += 1
        ch["total_words"] += fw["total_words"]
        for w, c in fw["words"].items():
            ch["words"][w] = ch["words"].get(w, 0) + c


def check_chapter_density(cfg, chapter_acc, findings):
    """Chapter scope = all scanned manuscript files sharing a directory.
    Only evaluated when 2+ files of that directory were scanned (a single
    file is already covered by the 'file' scope)."""
    dens = cfg.get("prose", {}).get("density", {})
    over = dens.get("over_limit", "error")
    if over == "off":
        return
    for d, ch in chapter_acc.items():
        if ch["files"] < 2:
            continue
        loc = d or "."
        words = ch["total_words"]
        pw = density_allowance(dens, "per_word", "chapter", words)
        ag = density_allowance(dens, "aggregate", "chapter", words)
        if pw is not None:
            for w, c in sorted(ch["words"].items()):
                if c > pw:
                    findings.append(Finding(
                        over, "P-DENSITY", loc, 0,
                        f"suspect word '{w}' appears {c}x across this "
                        f"chapter ({ch['files']} files, {words} words, "
                        f"allowed {pw}) — chapter-level clustering is a "
                        "machine tell"))
        if ag is not None:
            total = sum(ch["words"].values())
            if total > ag:
                findings.append(Finding(
                    over, "P-DENSITY", loc, 0,
                    f"{total} suspect-word occurrences across this chapter "
                    f"({words} words, allowed {ag}) — rewrite with plainer "
                    "vocabulary"))


def collect_all(root, cfg):
    proj = cfg.get("project", {})
    files = []
    for base in proj.get("manuscript_paths", []) + proj.get("notes_paths", []):
        d = os.path.join(root, base)
        for dirpath, _, names in os.walk(d):
            files += [os.path.join(dirpath, f) for f in names]
    return files


# ------------------------------------------------------------ main


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="*")
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show-config", action="store_true",
                    help="print the effective merged config and exit")
    ap.add_argument("--check-config", action="store_true",
                    help="lint the config (typos, regexes, severities)")
    ap.add_argument("--strict-markers", action="store_true",
                    help="treat workflow markers as ERRORs (delivery gate: "
                         "finished manuscript must contain none)")
    args = ap.parse_args()

    root = repo_root()
    cfg = load_config(root)
    if args.strict_markers:
        cfg["_strict_markers"] = True

    if args.show_config:
        print(json.dumps(cfg, indent=2))
        sys.exit(0)
    if args.check_config:
        probs = check_config(root, cfg)
        hard = [p for p in probs if not p.startswith("WARN: ")]
        for p in probs:
            print(f"[CONFIG] {p}")
        print(f"harness config: {'OK' if not hard else str(len(hard)) + ' problem(s)'}")
        sys.exit(1 if hard else 0)

    findings = []

    bib_keys, entries = parse_bibs(root, cfg)
    check_bib_entries(entries, cfg, findings)
    check_local_sources(root, entries, cfg, findings)

    targets = collect_all(root, cfg) if args.all else args.files
    chapter_acc = {}
    xref_acc = {"labels": {}, "refs": {}, "files": 0}
    for f in targets:
        check_file(root, f, cfg, findings, bib_keys, chapter_acc, xref_acc,
                   bib_entries=entries)
    check_chapter_density(cfg, chapter_acc, findings)
    finalize_xref(cfg, xref_acc, findings)

    errors = [f for f in findings if f.sev == "ERROR"]
    warns = [f for f in findings if f.sev == "WARN"]
    if args.json:
        print(json.dumps([f.to_dict() for f in findings], indent=2))
    else:
        for f in findings:
            print(str(f))
        print(f"harness: {len(errors)} error(s), {len(warns)} warning(s)")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
