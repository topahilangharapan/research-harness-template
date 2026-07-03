---
name: update-harness
description: >
  Update, extend, tune, or refactor the Research Harness itself — its rules,
  config fragments, enforcement wiring, hooks, docs, or this skill. Use when
  the user says "update the harness", "add a rule", "change the policy",
  "tune enforcement", "loosen/tighten a check", or asks why the harness
  blocked something and wants it changed.
---

# Updating the Research Harness

You are modifying the enforcement system itself. The doctor
(`.harness/engine/doctor.py`) verifies consistency mechanically and will
BLOCK any harness edit that leaves the system inconsistent — this skill
tells you how to make changes that pass it, in the right order.

## The harness surface (know what exists before touching anything)

| Part | Location | Role |
|---|---|---|
| Policy | `harness/` fragments + `harness/presets/` + `harness/rules.d/` | WHAT is enforced (the only place rules live) |
| Engine | `.harness/engine/validate.py`, `.harness/engine/citecheck.py`, `.harness/engine/doctor.py` | HOW rules are checked (generic; changes rarely) |
| Claude hooks | `.harness/hooks/` + `.harness/claude-settings-hooks.json` | Enforcement at tool-call time |
| Git gate | `.githooks/pre-commit` | Enforcement at commit time |
| CI | `.github/workflows/harness.yml` | Enforcement at push/PR time |
| Installer | `scripts/install-harness.sh` | Wires hooks into `.claude/settings.json` |
| Docs | `README.md`, `CLAUDE.md`, `harness/rules.d/README.md`, this skill | Must never go stale (doctor D-DOCPATH/D-DOCID) |

## Decision ladder — always prefer the highest rung

1. **Rule change** (new/changed/removed rule, severity, word list, path,
   scope keyword): edit JSON only. New rules go in `harness/rules.d/`;
   knob changes go in the owning fragment; shared lists in
   `harness/presets/`. NEVER implement a rule in Python if JSON can
   express it.
2. **Enforcement change** (when/where checks run): edit
   `harness/90-enforcement.json`. Only if a genuinely new check *kind* is
   needed, add a case arm in `.githooks/pre-commit` AND document the new
   id in `README.md` (doctor D-CHECKID/D-DOCID enforce this pairing).
3. **Engine change** (new rule *family* JSON can't express): extend
   `.harness/engine/validate.py`, expose it as config, add it to the
   relevant fragment, document it.
4. **Hook change**: edit `.harness/hooks/*` and/or
   `.harness/claude-settings-hooks.json`. NEVER edit
   `.claude/settings.json` directly — it is generated; update the source
   JSON and tell the user to re-run `scripts/install-harness.sh`
   (doctor D-STALE detects drift).

## Mandatory procedure

1. Read the current policy: `python3 .harness/engine/validate.py --show-config`
2. Make the change at the highest possible rung of the ladder.
3. Lint: `python3 .harness/engine/validate.py --check-config`
4. **Update every doc that mentions the changed behavior** — `README.md`,
   `CLAUDE.md`, `harness/rules.d/README.md`, and this skill if the
   surface table or ladder changed. Stale docs are a BLOCKING doctor error.
5. Prove behavior with a fixture: create a throwaway file that violates
   the new/changed rule, run `python3 .harness/engine/validate.py <file>`,
   confirm the expected finding, delete the fixture.
6. Run the doctor and fix everything it reports:
   `python3 .harness/engine/doctor.py`
7. If hooks changed: remind the user to re-run
   `bash scripts/install-harness.sh` and restart their Claude Code session.

## Hard constraints

- The doctor's verdict is authoritative. Never deliver a harness change
  while `doctor.py` exits non-zero; never disable a doctor check to make
  it pass.
- Policy lives ONLY in `harness/` — never hardcode a rule value in the
  engine or hooks.
- Loosening enforcement (removing checks, lowering severities, adding
  protected-path overrides) requires the user's explicit confirmation —
  restate what protection is being removed before doing it.
