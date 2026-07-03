---
name: fix-figure
description: >
  Repair a figure or diagram with visual defects: overlapping labels,
  misaligned arrows, crowded elements, routing errors, clipped content.
  Builds the manuscript, renders the figure page to an image, visually
  inspects it, fixes the source, and re-verifies with a second render.
  Use when the user says "fix the figure", mentions overlap/alignment/
  layout problems in a diagram, or a figure "looks wrong".
---

# fix-figure — Figure Repair (render–inspect–fix loop)

Never fix a figure blind: every change is verified by actually LOOKING at
the rendered output, twice.

## Activation sequence (in order)

1. **Intake.** Identify the figure: label, file path, or caption text.
   Resolve to the source file (search the manuscript tree for the label).
2. **Build command.** Read `workflow.build_command` from the harness
   config (`python3 .harness/engine/validate.py --show-config`). If it
   is empty, ask the user how the manuscript (or the standalone figure)
   is compiled, and suggest saving it to `harness/70-workflow.json` so
   the next run needs no question.
3. **Project precision rules.** If the project keeps a figure-conventions
   document (check the project docs and `harness/rules.d/`), read it and
   apply its rules. If a fix reveals a convention gap, propose adding a
   rule so the lesson is retained.
4. **First render.** Build; locate the page containing the figure;
   convert that page to PNG (e.g. `pdftoppm -r 200 -f N -l N`); VIEW the
   image.
5. **Inspection checklist.** Systematically check: element overlaps,
   label collisions and clearance, arrow/connector endpoints touching the
   faces they should, crossings through element bodies, clipped content
   at the canvas edge, crowding, font-size consistency, alignment of
   siblings.
6. **Diagnose and fix.** For each defect: state cause → exact source
   change. Apply fixes to the figure source only (never adjust global
   layout/margins to compensate — protected paths apply).
7. **Second render — mandatory.** Rebuild, re-render, VIEW again.
   Confirm each defect is gone and no new one appeared. If problems
   remain, loop (max 3 rounds, then report honestly what resists and
   why).
8. **Report.** Defects found → fixes applied → before/after status;
   plus any proposed new precision rule.

## Hard rules

- Never claim a figure is fixed without the second render — "the code
  looks right" is not verification.
- One figure per session unless the user asks for a batch.
- If the build fails for reasons unrelated to the figure, report the
  build error; do not "fix" unrelated files to force a build.
