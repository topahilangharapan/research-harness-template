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
3. **Read the target.** Every `@TODO` is an authoritative writing brief.
   Detect edit mode: any `@EDIT` markers or ORIGINAL/DELETE blocks mean
   this file came from the revise skill — announce the marker count and
   process them in change-id order.
4. **Blockers — STOP AND ASK, never work around:**
   - a briefed source key missing from the bibliography
   - a source the brief needs that the user has not provided
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
