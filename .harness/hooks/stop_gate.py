#!/usr/bin/env python3
"""Stop hook — turn-end gate.

Hard part (enforcement.stop_gate.block_on_validation_errors): if any
modified/untracked manuscript file has validator ERRORs when Claude tries
to end its turn, BLOCK (exit 2) and feed the findings back. This catches
anything that slipped past per-edit validation (e.g. shell edits) — no
turn can end with the manuscript in a violating state.

Soft part: non-blocking reminder when the tree is dirty (commit protocol).
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, ENGINE)
from validate import repo_root, load_config  # noqa: E402

root = repo_root()
try:
    data = json.load(sys.stdin)
except Exception:
    data = {}
if data.get("stop_hook_active"):
    sys.exit(0)  # already looping on this gate — don't deadlock

try:
    cfg = load_config(root)
    if not cfg.get("git", {}).get("enabled", True):
        sys.exit(0)
    dirty = subprocess.run(["git", "-C", root, "status", "--porcelain"],
                           capture_output=True, text=True,
                           timeout=10).stdout.strip()
    branch = subprocess.run(["git", "-C", root, "branch", "--show-current"],
                            capture_output=True, text=True,
                            timeout=5).stdout.strip()
except Exception:
    sys.exit(0)

if not dirty:
    sys.exit(0)

files = [ln[3:].strip().strip('"') for ln in dirty.splitlines()]
checkable = [os.path.join(root, f) for f in files
             if f.endswith((".tex", ".md", ".qmd", ".Rmd", ".bib"))]

sg = cfg.get("enforcement", {}).get("stop_gate", {})
if sg.get("block_on_validation_errors", True) and checkable:
    r = subprocess.run(
        [sys.executable, os.path.join(ENGINE, "validate.py")] + checkable,
        capture_output=True, text=True, timeout=180)
    if r.returncode != 0:
        print("Turn-end gate: modified manuscript files still have "
              "validator ERRORs. Fix them before finishing:\n"
              + (r.stdout or "") + (r.stderr or ""), file=sys.stderr)
        sys.exit(2)

trailer = cfg.get("git", {}).get("commit_trailer", "")
print(json.dumps({"systemMessage":
    f"harness: {len(files)} uncommitted change(s) on '{branch}'. "
    "Stage explicitly, commit"
    + (f" with trailer '{trailer}'" if trailer else "")
    + ", and push before ending the session."}))
sys.exit(0)
