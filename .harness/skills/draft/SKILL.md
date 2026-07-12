---
name: draft
description: >
  Write manuscript prose: turn @TODO scaffold instructions into
  citation-backed academic text, and process @EDIT revision markers left
  by the revise skill. Use when the user says "draft", "write section X",
  "fill in the content", or after scaffold/revise have placed markers.
---

# draft — Academic Writer

You produce the actual manuscript text. Every claim needs a source that
exists; every marker you consume must be fully resolved. The validator
re-checks each file you touch, automatically, and blocks violations.

## Activation sequence (in order)

1. **Policy.** Run `python3 .harness/engine/validate.py --show-config`.
   Internalize: prose rules (forbidden vocabulary, phrases, em-dash),
   `citations` (allowed types, required fields, bib files),
   `scope.statement`, `latex_commands` (required macro substitutions),
   `workflow.markers`.
2. **Intake.** If the target section/file and scope (just this section,
   or its subsections too) are not specified, ask and wait.
3. **Read the target.** If no scaffold exists yet (you are asked to
   "draft chapter 2" from nothing), do NOT create a monolithic file —
   run the scaffold step first: one directory per chapter, root file
   with `\chapter` + `\input` only, one `\section` per sub-file (the
   validator blocks monoliths regardless). Then draft sub-file by
   sub-file. Every `@TODO` is an authoritative writing brief.
   Detect edit mode: any `@EDIT` markers or ORIGINAL/DELETE blocks mean
   this file came from the revise skill — announce the marker count and
   process them in change-id order.
4. **Blockers — STOP AND ASK, never work around:**
   - a briefed source key missing from the bibliography
   - a source the brief needs that is not on the shelf (`references/`) —
     references-first: you may propose a web search for candidates, but
     found references are SUGGESTIONS ONLY; the user downloads the PDF
     into `references/` and only then may you add the bib entry (with
     its `file` field) and cite it — the validator (E-BIBSRC) and web
     gate enforce this regardless
   - a figure/table/asset slot whose file does not exist
   - the user's own methods/results referenced but never described
   - an `@EDIT[...|REWRITE]` with no matching ORIGINAL block (the
     validator flags this as E-MARKER — send the user back to revise)
   List all blockers in one numbered message; wait for resolution.
5. **Writing plan approval.** Present: target, scope, sources per claim
   (with keys), figures/tables to be created. WAIT for approval.
6. **Write.** Replace each `@TODO` with prose; each `@TODOCITE` with a
   real citation whose key exists. For REWRITE markers: write the new
   prose, then delete the marker AND the whole ORIGINAL block. For
   INSERT: write at the anchor, delete the marker. For DELETE blocks:
   remove the block; flag any orphaned labels/references it leaves.
7. **Human-writing self-check** (judgment tells the validator cannot
   catch — the word/pattern tiers it CAN catch will block you anyway):
   - vary list and sentence lengths; break the rule-of-three reflex
   - plain copulas: is/are/has — no elegant paraphrase of "to be"
   - repeat a noun naturally instead of rotating synonyms
   - no significance inflation ("reflects broader trends") and no
     legacy/impact padding at section ends — state the specific fact
   - no interpretation appended to facts unless attributed to a named,
     cited source
   - prefer one precise, checkable fact over three vague generalities
   - suspect words ("key", "rich", "notably", ...) are density-governed:
     one literal/technical use is fine, clustering blocks (P-DENSITY) —
     when the validator flags a cluster, vary the wording, do not just
     shuffle the word to an adjacent paragraph
8. **Validate before delivery.** Run
   `python3 .harness/engine/validate.py <files you touched>` — zero
   errors required, and no marker may remain in anything you consumed.
   Then report: files changed, sources cited, warnings remaining.

## DOCX targets

For Word manuscripts, all editing goes through
`.harness/engine/docxtool.py` (Edit/Write are blocked on .docx):

- Read briefs: `docxtool.py cat <file>` (marker paragraphs are tagged
  `[MARKER]`); inspect one paragraph with `show <file> N`.
- Write prose: `insert <file> N --text "..."` for new paragraphs;
  `replace <file> N --text "..."` for rewrites. THE PLACEHOLDER
  CONTRACT: if a paragraph contains citation fields, `show` renders
  them as `{{field:k}}` and your replacement text must carry every one
  exactly once — the tool refuses otherwise, so a rewrite cannot drop
  a citation.
- Cite: `add-cite <file> N --key <bibkey>` appends a native
  Zotero-compatible field (key must exist in the bib; the tool refuses
  unknown keys). If `docx.citations.allow_generated_fields` is false,
  leave a `@TODOCITE` marker paragraph for the human instead.
- Consume markers: after drafting a brief, `delete <file> N` removes
  the marker paragraph; ORIGINAL/DELETE blocks are removed the same way.
- The tool validates after every edit (exit 2 = fix the findings before
  continuing — same contract as the per-edit hook).

## Hard rules

- Never invent a reference. No source → blocker → ask. The citation
  verifier (`.harness/engine/citecheck.py`) will expose fabricated
  DOIs/ISBNs in CI regardless.
- Never leave a consumed marker, ORIGINAL, or DELETE block in delivered
  content — `validate.py --strict-markers` is the delivery gate.
- Respect the configured command substitutions and label prefixes.
- Prose violations in manuscript paths BLOCK — do not ask the user to
  loosen the policy mid-draft; finish clean or surface the conflict.
- Scope: if a brief drags you outside `scope.statement`, stop and ask.
