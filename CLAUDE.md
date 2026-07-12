# CLAUDE.md — Research Project Instructions

This project uses **Paramasastra**, a research harness: every mechanically-checkable rule
is declared in `harness.json` and enforced by code (Claude Code hooks, git
pre-commit, CI). Hook blocks are authoritative — fix the violation, never
work around a block.

## Ground rules

1. **Read the `harness/` config directory first.** It is the live policy,
   split by concern: project paths, git workflow, protected paths, prose
   rules, citations, scope, LaTeX conventions, enforcement wiring. Inspect
   the effective merged policy with
   `python3 .harness/engine/validate.py --show-config`.
2. **Scope**: see `harness/50-scope.json`. If a topic is borderline,
   STOP and ask before writing.
3. **Citations**: never invent a reference. Every cite key must already
   exist in the configured bib file(s); every entry needs its required
   identifier fields (DOI/ISBN), which CI verifies against Crossref and
   OpenLibrary. If no source exists, say so instead of citing.
4. **Git**: never edit on a protected branch; stage files explicitly;
   include the configured commit trailer; push the feature branch at
   session end.
5. **Prose**: academic register; no em-dashes; no forbidden AI vocabulary
   (the validator enforces this on every edit in manuscript paths).
6. **Word manuscripts (.docx)**: never Edit/Write a .docx — it is a zip
   of XML and the gate blocks it. Use
   `python3 .harness/engine/docxtool.py` (cat/show/outline/cites/
   replace/insert/delete/add-cite/new). `replace` must carry every
   `{{field:k}}` citation placeholder shown by `show`. Citations are
   native Zotero/Word fields and must resolve to entries in the bib;
   the validator reports .docx findings by paragraph index.

## Writing workflow

Manuscript work goes through the lifecycle skills (in `.claude/skills/`
after install): **scaffold** (structure + @TODO briefs for new content) →
**draft** (prose) → **review** (audit + triage). Changes to written
content go through **revise** (places @EDIT markers) → draft → review —
never rewrite written prose directly. Broken marker pairs and leftover
markers are blocked by the validator (`E-MARKER`, `--strict-markers`).
Figures are repaired with **fix-figure** (render–inspect–fix, verified
visually twice).

## Judgment rules (not mechanically enforceable — follow deliberately)

- Verify that cited sources actually support the claims attributed to them.
- Keep argumentation within the declared research scope.
- Prefer primary sources; summarize honestly; never overstate findings.

## Layout

- `paper/` or `src/` — the manuscript; this is what the harness governs
  (prose rules block here)
- `references.bib` — bibliography (typed policy in `harness.json`)
- `.harness/` — enforcement engine; do not edit unless asked
