#!/usr/bin/env python3
"""Pramana doctor — self-consistency checker.

The harness governs the manuscript; the doctor governs THE HARNESS.
It makes 'update the harness' a safe operation: after any change to
config, engine, hooks, docs, or skill, the doctor verifies that every
part still agrees with every other part. It runs automatically (PostToolUse
hook on harness-surface edits, pre-commit 'doctor' check, CI), so an
inconsistent or stale-doc harness update cannot land — regardless of
whether the AI followed the update-harness skill.

Checks:
  D-CONFIG    effective config passes check_config (typos, regexes, ...)
  D-CHECKID   every enforcement.pre_commit.checks id is implemented in
              .githooks/pre-commit (and vice-versa documented in README)
  D-HOOKREF   every hook command in claude-settings-hooks.json points to
              an existing script; hook scripts are present
  D-DOCPATH   every repo path referenced in docs/skill (outside code
              fences) exists — no stale documentation
  D-DOCID     README documents every implemented pre-commit check id
  D-STALE     .claude/settings.json (if installed) matches
              claude-settings-hooks.json — else re-run installer   [warn]
  D-EXEC      pre-commit / engine / hook scripts are executable      [warn]

Exit codes: 0 = healthy (warnings allowed), 1 = inconsistencies.
"""
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
from validate import repo_root, load_config, check_config, parse_jsonc_file  # noqa: E402

import glob as _glob

# Docs and instruction files whose path references must stay fresh.
# Every skill shipped with the harness is linted automatically.
DOC_FILES = ["README.md", "CLAUDE.md", "harness/rules.d/README.md"]


def doc_files(root):
    skills = sorted(os.path.relpath(p, root) for p in
                    _glob.glob(os.path.join(root, ".harness", "skills",
                                            "*", "SKILL.md")))
    return DOC_FILES + skills
PRECOMMIT = ".githooks/pre-commit"
HOOKS_JSON = ".harness/claude-settings-hooks.json"
SETTINGS = ".claude/settings.json"

PATH_TOKEN = re.compile(
    r"(?<![\w/])((?:\.harness|harness|\.githooks|\.github|scripts)/"
    r"[A-Za-z0-9_./-]*[A-Za-z0-9_])")


class Problem:
    def __init__(self, sev, code, msg):
        self.sev, self.code, self.msg = sev, code, msg

    def __str__(self):
        return f"[{self.sev}] {self.code}: {self.msg}"


def strip_fences(text):
    """Remove fenced code blocks and inline backtick spans that contain
    examples (hypothetical paths are allowed there)."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    return text


def implemented_precommit_ids(root):
    """Parse case-arm ids out of .githooks/pre-commit."""
    fp = os.path.join(root, PRECOMMIT)
    if not os.path.isfile(fp):
        return None
    src = open(fp, encoding="utf-8").read()
    case = re.search(r'case\s+"\$CHECK"\s+in(.*?)esac', src, re.S)
    if not case:
        return set()
    return {m.group(1) for m in re.finditer(r"^\s*([a-z_]+)\)", case.group(1), re.M)}


def main():
    root = repo_root()
    probs = []

    # D-CONFIG — the policy itself is sane
    try:
        cfg = load_config(root)
        for p in check_config(root, cfg):
            if p.startswith("WARN: "):
                probs.append(Problem("WARN", "D-CONFIG", p[6:]))
            else:
                probs.append(Problem("ERROR", "D-CONFIG", p))
    except SystemExit as e:
        print(f"[ERROR] D-CONFIG: {e}")
        sys.exit(1)

    # D-CHECKID — declared enforcement steps are actually implemented
    impl = implemented_precommit_ids(root)
    if impl is None:
        probs.append(Problem("ERROR", "D-CHECKID", f"{PRECOMMIT} missing"))
        impl = set()
    else:
        declared = set(cfg.get("enforcement", {}).get("pre_commit", {})
                       .get("checks", []))
        for c in declared - impl:
            probs.append(Problem(
                "ERROR", "D-CHECKID",
                f"enforcement.pre_commit.checks declares '{c}' but "
                f"{PRECOMMIT} does not implement it"))

    # D-HOOKREF — Claude hook wiring points at real scripts
    hj = os.path.join(root, HOOKS_JSON)
    if not os.path.isfile(hj):
        probs.append(Problem("ERROR", "D-HOOKREF", f"{HOOKS_JSON} missing"))
    else:
        blob = parse_jsonc_file(hj)
        for event, groups in blob.get("hooks", {}).items():
            for g in groups:
                for h in g.get("hooks", []):
                    m = re.search(r"\$CLAUDE_PROJECT_DIR/([^\"]+)", h.get("command", ""))
                    if m and not os.path.isfile(os.path.join(root, m.group(1))):
                        probs.append(Problem(
                            "ERROR", "D-HOOKREF",
                            f"{HOOKS_JSON} ({event}) references missing "
                            f"script '{m.group(1)}'"))

    # D-DOCPATH — no stale path references in docs/skills
    for doc in doc_files(root):
        fp = os.path.join(root, doc)
        if not os.path.isfile(fp):
            probs.append(Problem("ERROR", "D-DOCPATH", f"expected doc '{doc}' missing"))
            continue
        body = strip_fences(open(fp, encoding="utf-8").read())
        for m in PATH_TOKEN.finditer(body):
            ref = m.group(1).rstrip(".,;:")
            if any(ch in ref for ch in "*<>$"):
                continue
            if not os.path.exists(os.path.join(root, ref)):
                probs.append(Problem(
                    "ERROR", "D-DOCPATH",
                    f"{doc} references '{ref}' which does not exist — "
                    "stale documentation"))

    # D-DOCID — README documents every implemented check id
    readme_fp = os.path.join(root, "README.md")
    if os.path.isfile(readme_fp):
        readme = open(readme_fp, encoding="utf-8").read()
        for c in sorted(impl - {"*"}):
            if c not in readme:
                probs.append(Problem(
                    "ERROR", "D-DOCID",
                    f"pre-commit implements check '{c}' but README.md "
                    "does not document it"))

    # D-TRIGGER — every skill_triggers key maps to a shipped skill
    for skill in cfg.get("workflow", {}).get("skill_triggers", {}):
        if not os.path.isfile(os.path.join(
                root, ".harness", "skills", skill, "SKILL.md")):
            probs.append(Problem(
                "ERROR", "D-TRIGGER",
                f"workflow.skill_triggers declares '{skill}' but "
                f".harness/skills/{skill}/SKILL.md does not exist"))

    # D-STALE — installed Claude hooks drifted from source of truth
    st = os.path.join(root, SETTINGS)
    if os.path.isfile(st) and os.path.isfile(hj):
        try:
            installed = json.load(open(st)).get("hooks")
            desired = parse_jsonc_file(hj).get("hooks")
            if installed != desired:
                probs.append(Problem(
                    "WARN", "D-STALE",
                    f"{SETTINGS} hooks differ from {HOOKS_JSON} — "
                    "re-run scripts/install-harness.sh"))
        except Exception as e:
            probs.append(Problem("WARN", "D-STALE", f"cannot compare: {e}"))

    # D-EXEC — enforcement scripts are executable
    for s in [PRECOMMIT, "scripts/install-harness.sh",
              ".harness/engine/validate.py", ".harness/engine/citecheck.py",
              ".harness/engine/doctor.py"]:
        fp = os.path.join(root, s)
        if os.path.isfile(fp) and not os.access(fp, os.X_OK):
            probs.append(Problem("WARN", "D-EXEC",
                                 f"'{s}' not executable (chmod +x)"))

    errors = [p for p in probs if p.sev == "ERROR"]
    for p in probs:
        print(str(p))
    print(f"doctor: {len(errors)} error(s), {len(probs) - len(errors)} "
          f"warning(s) — harness is "
          f"{'INCONSISTENT' if errors else 'consistent'}")
    sys.exit(1 if errors else 0)


if __name__ == "__main__":
    main()
