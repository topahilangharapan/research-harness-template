---
name: revise
description: >
  Plan changes to ALREADY-WRITTEN manuscript content: place @EDIT markers
  and preserve original prose in ORIGINAL/DELETE blocks for the draft
  skill to execute. Use when the user says "revise", "change section X",
  "rewrite this part", "expand/shorten/delete content", or wants to modify
  existing text. Writes NO prose itself.
---

# revise — Change Planner

The only entry point for changing written content. You read, mark, and
hand off — the draft skill writes. This separation keeps every change
reviewable: the marker states the intent, the ORIGINAL block preserves
what it replaces, and the validator enforces the pairing (E-MARKER).

## Workflow position

scaffold (new content) → draft → review → **revise** (changes) → draft → review

## Activation sequence (in order)

1. **Policy.** Run `python3 .harness/engine/validate.py --show-config`;
   note `workflow.markers` (exact tokens) and `scope.statement`.
2. **Intake.** Require both before proceeding: the SCOPE (which
   section(s)/file(s)) and the CHANGE BRIEF (for each change: what —
   rewrite/expand/shorten/delete/insert; where; why). Ask for whatever
   is missing and wait.
3. **Read targets.** If pre-existing @EDIT/ORIGINAL/DELETE blocks are
   found, report them and ask whether to keep or replace them.
4. **Change Plan approval.** Present a table: change-id (chg-001, ...),
   operation, location (file + heading/paragraph), instruction summary,
   sources involved. WAIT for approval.
5. **Place markers.** For each approved change, in id order:
   - REWRITE: put the `@EDIT[id|REWRITE]` instruction above the prose,
     wrap the prose it replaces in ORIGINAL begin/end block markers
     (commented out so the manuscript still builds)
   - INSERT: place `@EDIT[id|INSERT]` with an unambiguous anchor
   - DELETE: wrap the doomed prose in DELETE begin/end block markers
     (commented out)
6. **Verify the contract.** Run
   `python3 .harness/engine/validate.py <files>` — every REWRITE must
   pair with its ORIGINAL block, every block must close (E-MARKER
   errors mean you placed markers wrong; fix before handing off).
7. **Handoff.** Report the marker inventory and instruct the user to run
   the **draft** skill to execute the changes.

## Marker syntax (tokens come from harness/70-workflow.json)

```latex
% @EDIT[chg-001|REWRITE] Tighten this paragraph to 3 sentences; keep the
%       citation of mano2013; remove the analogy.
% ==== ORIGINAL chg-001 ====
% The original paragraph text, commented out, preserved verbatim...
% ==== END ORIGINAL chg-001 ====
```

```markdown
<!-- @EDIT[chg-002|INSERT] After the paragraph ending "...results.",
     add 2 paragraphs on limitations, citing smith2021. -->
```

## Hard rules

- NO prose. If a change is small enough that you are tempted to just
  make it, you still place a marker — the draft skill executes, the
  audit trail survives.
- Never delete original text: REWRITE/DELETE targets are preserved in
  commented blocks until draft consumes them.
- Change-ids are unique and sequential within the session.
- Branch gate and protected paths apply as always.
