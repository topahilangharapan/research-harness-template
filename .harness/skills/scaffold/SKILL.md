---
name: scaffold
description: >
  Design the structure of a new chapter or section of the manuscript BEFORE
  any prose exists: headings, labels, source-to-section mapping, and @TODO
  writing instructions for the draft skill. Use when the user says
  "scaffold", "outline", "plan the chapter/section", "design the structure",
  or wants to start a new part of the thesis/paper. Never use on
  already-written content (that is the revise skill's job).
---

# scaffold — Structure Architect

You design the intellectual skeleton. You write NO prose — only structure
and machine-checkable writing instructions. The draft skill turns them into
text later.

## Activation sequence (in order)

1. **Policy.** Run `python3 .harness/engine/validate.py --show-config`.
   Note: `project.manuscript_paths` (where files go), `scope.statement`
   (what the manuscript may cover), `labels.prefixes`, `citations`
   (allowed source types), `workflow.markers` (marker tokens), and any
   `custom_rules` that constrain file structure.
2. **Intake.** If the user did not specify the chapter/section and its
   working title, ask. Do not proceed without it.
3. **Source survey.** Read the configured bibliography file(s) and list
   which sources could support which planned parts. If the project keeps
   source PDFs in a folder, list its contents. Report gaps: planned
   claims with no available source.
4. **Scope check.** Every planned heading must fall inside
   `scope.statement`. Borderline → STOP and ask before including it.
5. **Plan approval.** Present the Scaffold Plan and WAIT for approval:
   headings with their labels (use the configured prefixes), the
   source(s) supporting each part, planned figures/tables with labels,
   and the exact file paths to be created.
6. **Execute.** Only after approval, create the files — MODULAR, never
   monolithic. For LaTeX the layout is one directory per chapter, one
   sub-file per section, a root file of structure only (the validator's
   `latex_modularity` check blocks anything else):

   ```
   paper/ch2/ch2.tex            % ROOT: \chapter{...} + \input calls ONLY
   paper/ch2/sec-related-work.tex   % ONE \section + its @TODO briefs
   paper/ch2/sec-methodology.tex
   paper/ch2/sec-summary.tex
   ```

   Each section gets `@TODO` instruction markers (inside comments of the
   host format) and `@TODOCITE` where a citation will be needed. Also
   follow any structure rules in `harness/rules.d/` and `file_shapes`.
7. **Report.** List files created, labels assigned, source coverage, and
   remaining gaps. The validator runs automatically on each file you
   write; fix anything it blocks.

## Marker format (write instructions this way)

```latex
% @TODO Explain the register-transfer model: definition, components,
%       one worked example. Sources: mano2013 ch.8. Min 2 paragraphs.
%       @TODOCITE mano2013
```

```markdown
<!-- @TODO Summarize related work on X; contrast with our approach.
     Sources: smith2021, lee2023. Min 3 paragraphs. -->
```

Each @TODO must state: what to write, which source keys support it, and
a minimum length. An instruction the draft skill cannot execute without
asking questions is a defective instruction.

## Hard rules

- NO prose, ever — instructions only. If you catch yourself writing a
  sentence destined for the manuscript, stop and convert it into a @TODO.
- Never place a real citation — mark with `@TODOCITE` + the intended key.
  If the key does not exist in the bibliography yet, say so in the plan.
- Labels must use the configured prefixes; the validator warns otherwise.
- The git branch gate and all protected-path rules apply; hook blocks are
  authoritative.
- Handoff: tell the user the next step is the **draft** skill, section by
  section.
