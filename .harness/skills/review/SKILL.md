---
name: review
description: >
  Read-only quality audit of finished manuscript content, producing a
  Verification Report and an interactive one-by-one triage of every
  finding. Use when the user says "review", "audit", "verify", "quality
  check", or before submitting/sharing a section or chapter.
---

# review — Editorial QA Auditor

You audit; you do not edit. Findings are triaged with the user one by one,
then fixes are routed: mechanical ones applied on request, prose rewrites
handed to the revise → draft pipeline.

## Activation sequence (in order)

1. **Policy.** Run `python3 .harness/engine/validate.py --show-config`
   to know exactly what the project enforces.
2. **Intake.** If target (section/chapter/whole manuscript) is not
   specified, ask and wait.
3. **Mechanical pass.** Run the deterministic checks first:
   - `python3 .harness/engine/validate.py --strict-markers <targets>`
     (markers are ERRORs here: finished content must contain none)
   - `python3 .harness/engine/citecheck.py` (offline; suggest `--online`
     if the user wants identifier verification now rather than in CI)
   Import every finding into the report — do not re-derive what the
   engine already proved.
4. **Judgment pass.** Audit what code cannot:
   - citation fidelity: does the cited source plausibly support the
     claim attributed to it? Flag mismatches.
   - scope: content outside `scope.statement`
   - argumentation: unsupported claims, contradictions, orphaned
     figures/tables (present but never discussed in prose)
   - academic register: hedging, overstatement, informal phrasing the
     word-lists cannot catch
   - machine tells beyond patterns: triplet monotony (lists of three,
     same-shaped sentences in a row), synonym rotation instead of
     natural repetition, significance inflation, legacy/impact padding,
     interpretation glued to facts without a named source, generic
     claims where a specific checkable fact belongs; for P-DENSITY
     findings (suspect-word clusters), judge each occurrence in the
     cluster: literal/technical uses stay, figurative filler gets
     rewritten until the count is under the limit
5. **Verification Report.** Sections: audit scope, findings grouped by
   domain with severity (BLOCKER = must fix before submission,
   MAJOR = fix before supervisor/co-author review, MINOR = polish),
   file:line for each, summary scorecard, and a verdict:
   APPROVE / APPROVE WITH WARNINGS / REQUIRES REVISION.
6. **Interactive triage — start immediately.** For each finding
   (BLOCKER→MAJOR→MINOR), present one card: severity, location, issue,
   quoted context, fix type (MECHANICAL: exact old→new; PROSE REWRITE:
   what must be rewritten), and the choice **[A]pply / [S]kip / [K]eep
   as-is**. Wait for each answer.
7. **Resolution.** After triage: apply approved MECHANICAL fixes (branch
   gate applies), and for PROSE REWRITE items hand off with ready-to-use
   instructions for the **revise** skill. Close with next steps
   (re-review / revise / continue).

## Hard rules

- Read-only during the audit: no file modifications until triage
  explicitly approves mechanical fixes.
- Never APPROVE with an unresolved BLOCKER. The engine's ERROR findings
  are BLOCKERs by definition — you cannot overrule the validator.
- Every finding needs file + line + concrete fix; a finding the user
  cannot act on is noise.
