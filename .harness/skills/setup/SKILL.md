---
name: setup
description: >
  One-time initializer for a fresh clone of the Paramasastra template:
  interview the user for the project's identity, then rewrite every
  project-specific touchpoint consistently (harness config, LaTeX
  metadata, docs). Use when the user says "set up the project",
  "initialize the template", "new project from template", or
  "first-time setup". Never use it to change harness rules (that is
  update-harness) or to create chapters (that is scaffold).
---

# setup: initialize a new project from the template

You convert template placeholders into this project's real values, once,
before any writing starts. Everything you touch is user-config surface
(`harness/` fragments, `config/settings.tex`, docs). You never touch the
engine, hooks, or `_internals/`.

## Activation sequence (in order)

1. **Read state.** Run `python3 .harness/engine/validate.py --show-config`.
   Read `harness/00-project.json`, `harness/50-scope.json`, and
   `config/settings.tex`. Run `git branch --show-current` and
   `git status --porcelain`.
2. **Freshness check.** Three sentinels mark a fresh template:
   `project.name` is `my-research-paper`, `scope.statement` starts with
   `DESCRIBE YOUR RESEARCH SCOPE HERE`, and `\papertitle` is
   `Working Title`.
   - All three present: fresh clone, proceed.
   - Some present: partially configured. List the values that are already
     customized; change those only with per-value confirmation.
   - None present: the project is already configured. STOP and ask
     whether the user really wants to reconfigure; if yes, every change
     is an overwrite and needs explicit confirmation.
3. **Branch gate.** If the current branch is in `git.protected_branches`,
   run `git checkout -b chore/setup-project` BEFORE the first edit (the
   branch gate and bash guard block all edits on protected branches).
   If the working tree is dirty, warn the user first.
4. **Intake.** ONE batch of core questions, at most six, each with a
   computed default so a short answer suffices:
   - Project name/slug (default: repo directory name or git remote name)
   - Paper title
   - Author (default: current `\paperauthor` in `config/settings.tex`,
     else `git config user.name`)
   - Affiliation (optional; empty is valid)
   - Research scope: 1 to 3 sentences covering topic, methods, and
     boundaries, plus optional deny keywords
   - Manuscript format: LaTeX (default) or Word (.docx)

   Then ONE defaults gate: list the advanced settings with their current
   values (manuscript path, bib file and citation policy, protected
   branches and prefixes, commit trailer, build command and main file,
   web gate mode, CI online citation check, CI workflow name) and ask
   "accept all, or customize some?". Only the items the user names get
   follow-up questions. Hard cap: two interview rounds total.
5. **Plan approval.** Present a change table (file, key, current value,
   new value), required rows first, and WAIT for explicit approval.
6. **Apply.** The `harness/` fragments are JSONC with load-bearing
   comments: make surgical Edit replacements of the exact old string,
   NEVER parse and re-dump a file. Order:
   1. `harness/00-project.json`: `project.name`; `manuscript_paths` and
      `formats` only if changed
   2. `harness/50-scope.json`: `scope.statement`, `deny_keywords`
   3. `config/settings.tex`: `\papertitle`, `\paperauthor`,
      `\paperaffiliation`, `\paperdate` (LaTeX mode only)
   4. Only if the defaults gate opened them: `harness/10-git.json`,
      `harness/40-citations.json`, the build block in
      `harness/70-workflow.json`, `harness/90-enforcement.json`, and the
      `name:` line of `.github/workflows/harness.yml`. Loosening
      enforcement (web gate, CI checks) requires restating what
      protection is removed and getting a separate confirmation.
   5. Docs: rewrite the `README.md` intro for the new project (keep the
      harness documentation sections), and add a short project-context
      paragraph to `CLAUDE.md` after the heading (keep the rules
      sections intact).
7. **Install and verify.** Run `bash scripts/install-harness.sh`
   (idempotent), then `python3 .harness/engine/doctor.py` and
   `python3 .harness/engine/validate.py --check-config`. Echo the
   effective values back with `--show-config`. In LaTeX mode, offer
   `bash scripts/build.sh` to prove the title page compiles; skip
   gracefully when latexmk is not installed.
8. **Commit.** On the setup branch, stage each changed file explicitly
   (bulk add is forbidden), commit with the configured
   `git.commit_trailer`, and tell the user to merge or PR into the main
   branch themselves. If the user declines, list the modified files and
   stop.
9. **Report.** Summarize what changed and the values now in force, list
   open items (for example an empty affiliation), and hand off: the next
   step is the **scaffold** skill for chapter 1.

## Touchpoint map

| File | Keys | When | Fresh-template value |
|---|---|---|---|
| `harness/00-project.json` | `project.name`, `manuscript_paths`, `formats` | required | `my-research-paper` |
| `harness/50-scope.json` | `scope.statement`, `deny_keywords` | required | `DESCRIBE YOUR RESEARCH SCOPE HERE...` |
| `config/settings.tex` | `\papertitle`, `\paperauthor`, `\paperaffiliation`, `\paperdate` | required (LaTeX mode) | `Working Title` |
| `harness/10-git.json` | `protected_branches`, `branch_prefixes`, `commit_trailer` | defaults gate | |
| `harness/40-citations.json` | `bib_files`, `allowed_types`, `required_fields` | defaults gate | |
| `harness/70-workflow.json` | `build.main`, `build.command`, `build.dir` | defaults gate / Word mode | `main.tex` |
| `harness/90-enforcement.json` | `ci.citations_online`, `web_gate.mode` | defaults gate | |
| `.github/workflows/harness.yml` | `name:` | defaults gate | `Paramasastra` |
| `README.md`, `CLAUDE.md` | project intro / context paragraph | required | template wording |

## Word (.docx) mode

When the user picks Word as the manuscript format:

- Skip the `config/settings.tex` metadata edits (LaTeX-only).
- Point `workflow.build.main` in `harness/70-workflow.json` at the
  planned `.docx` path; the build then snapshots the validated file and
  uses `docx_command` for PDF export when LibreOffice is present.
- Optionally set `formats.latex` to `false` in `harness/00-project.json`
  for a Word-only project.
- `harness/65-docx.json` already ships with `formats.docx: true`; no
  edit is needed in the common case.
- Do NOT create the `.docx` file: the scaffold skill creates it later
  via `.harness/engine/docxtool.py new`.

## Hard rules

- Never edit `_internals/`, `template/`, or `main.tex`; setup needs none
  of them (title and author flow through `config/settings.tex`).
- Never overwrite a non-placeholder value without per-value
  confirmation; a second run must never destroy a configured project.
- Preserve JSONC comments: surgical string edits only.
- Never edit `.claude/settings.json`, `.claude/skills/`, or
  `.claude/commands/` directly; they are generated, so change the source
  under `.harness/` and re-run `scripts/install-harness.sh`.
- The doctor's verdict is authoritative: never finish while
  `python3 .harness/engine/doctor.py` exits non-zero.
- At most two interview rounds; batch the questions, never drip them.

## Example

```
User: set up the project

setup: This is a fresh clone (all three placeholders present).
       Creating branch chore/setup-project. Core questions:
       1. Project name [paramasastra-fork]? ...
       ...
User: name llm-eval-paper, title "Evaluating LLM Graders",
      author as configured, no affiliation,
      scope: "Reliability of LLM-as-judge scoring for code review;
      methods: paired human baselines; boundary: no RLHF work.",
      LaTeX. Accept defaults.

setup: Change table ... approve?
User: yes

setup: [applies edits, runs installer + doctor + check-config]
       All green. Committed on chore/setup-project (5 files).
       Next: run the scaffold skill for chapter 1.
```
