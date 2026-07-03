#!/usr/bin/env python3
"""UserPromptSubmit — inject a per-turn digest built FROM the harness
config, so the reminder always matches the live policy (edit JSON, digest
follows). Also matches the user's prompt against workflow.skill_triggers
and injects a hard directive to invoke the matching lifecycle skill —
skill activation no longer depends on the model noticing on its own.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
from validate import repo_root, load_config  # noqa: E402

root = repo_root()
try:
    cfg = load_config(root)
except Exception:
    sys.exit(0)

try:
    prompt = (json.load(sys.stdin) or {}).get("prompt", "")
except Exception:
    prompt = ""

dig = cfg.get("enforcement", {}).get("digest", {})
if not dig.get("enabled", True):
    sys.exit(0)

try:
    branch = subprocess.run(["git", "-C", root, "branch", "--show-current"],
                            capture_output=True, text=True,
                            timeout=5).stdout.strip()
except Exception:
    branch = "?"

git = cfg.get("git", {})
cit = cfg.get("citations", {})
proj = cfg.get("project", {})
lines = [f"<harness-reminder project='{proj.get('name', '?')}' branch='{branch}'>"]
if git.get("enabled", True) and git.get("require_feature_branch", True):
    lines.append(f"1. Never edit files on {git.get('protected_branches')}; "
                 "stage explicitly (no `git add .`); commit trailer: "
                 f"{git.get('commit_trailer', '')}")
scope = cfg.get("scope", {}).get("statement", "").strip()
if scope:
    lines.append(f"2. SCOPE: {scope} Borderline topic => STOP and ask.")
if cit.get("allowed_types"):
    lines.append(f"3. Citations: allowed bib types {cit['allowed_types']}; "
                 "every cite key must already exist in "
                 f"{cit.get('bib_files')}; never invent a reference — "
                 "identifiers (DOI/ISBN) are verified online in CI.")
lines.append("4. Prose: no em-dashes, no forbidden AI vocabulary, no machine "
             "constructions — validator enforces on every edit. Judgment "
             "tells it cannot catch: vary list lengths (break the "
             "rule-of-three), plain copulas (is/are/has), natural noun "
             "repetition over synonym rotation, no significance inflation "
             "or legacy padding, one precise checkable fact beats three "
             "generalities.")
if cfg.get("workflow", {}).get("markers"):
    lines.append("5. Workflow: scaffold -> draft -> review; changes to "
                 "written content go through revise (markers), never "
                 "direct rewrites. Markers must be gone before delivery "
                 "(strict gate enforces).")
lines.append("6. Hook blocks are authoritative — fix the violation, never "
             "work around a block.")
lines += dig.get("extra_lines", [])

# Skill auto-activation directive (workflow.skill_triggers)
low = prompt.lower()
matched = [skill for skill, kws in
           cfg.get("workflow", {}).get("skill_triggers", {}).items()
           if any(k.lower() in low for k in kws)]
for skill in matched:
    lines.append(
        f"DIRECTIVE: this request matches the '{skill}' skill. Invoke the "
        f"Skill tool with '{skill}' BEFORE doing anything else and follow "
        "its activation sequence exactly. Do not improvise the workflow.")

lines.append("</harness-reminder>")
print("\n".join(lines))
