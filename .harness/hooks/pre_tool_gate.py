#!/usr/bin/env python3
"""PreToolUse gate — config-driven. Reads harness.json:
  git.require_feature_branch / protected_branches / forbid_bulk_add /
  block_commit_on_protected, protected_paths.deny / confirm / override_env.
Blocks with exit 2 (stderr fed back to Claude); 'confirm' paths emit
permissionDecision: ask.
"""
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "engine"))
from validate import repo_root, load_config, relpath, norm  # noqa: E402


def branch(root):
    try:
        return subprocess.run(["git", "-C", root, "branch", "--show-current"],
                              capture_output=True, text=True,
                              timeout=10).stdout.strip()
    except Exception:
        return ""


def deny(msg):
    print(msg, file=sys.stderr)
    sys.exit(2)


def ask(reason):
    print(json.dumps({"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "ask",
        "permissionDecisionReason": reason}}))
    sys.exit(0)


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        sys.exit(0)
    root = repo_root()
    try:
        cfg = load_config(root)
    except Exception:
        sys.exit(0)

    git = cfg.get("git", {})
    pp = cfg.get("protected_paths", {})
    prot = git.get("protected_branches", ["main", "master"])
    tool = data.get("tool_name", "")
    ti = data.get("tool_input", {}) or {}

    # WEB GATE — references-first policy: no silent internet access
    wg = cfg.get("enforcement", {}).get("web_gate", {})
    if tool in ("WebFetch", "WebSearch"):
        mode = wg.get("mode", "ask")
        if mode == "deny":
            deny("BLOCKED by harness (web_gate: deny): internet access is "
                 "disabled. Work from the local shelf (references/). If it "
                 "is insufficient, tell the user which claims lack sources "
                 "and ask them to change web_gate.mode or add sources.")
        if mode == "ask":
            ask("References-first policy: web access is only for reference "
                "DISCOVERY after the local shelf (references/) is "
                "insufficient. Found references may only be SUGGESTED — "
                "the user downloads them into references/ before they can "
                "be cited. Approve this web request?")
        sys.exit(0)

    if tool == "Bash":
        cmd = ti.get("command", "")
        if git.get("enabled", True):
            if git.get("forbid_bulk_add", True) and \
                    re.search(r"\bgit\s+add\s+(\.|-A\b|--all\b)", cmd):
                deny("BLOCKED by harness (git.forbid_bulk_add): stage files "
                     "explicitly — git add <file> <file> ...")
            if git.get("block_commit_on_protected", True) and \
                    re.search(r"\bgit\s+commit\b", cmd) and branch(root) in prot:
                deny(f"BLOCKED by harness: committing on '{branch(root)}' is "
                     "forbidden. Create a branch: git checkout -b "
                     f"{'|'.join(git.get('branch_prefixes', ['feat/']))}<topic>")

        # Web gate also covers shell fetchers
        if wg.get("block_bash_fetch", True) and \
                re.search(r"\b(curl|wget|httpie|http)\s", cmd):
            deny("BLOCKED by harness (web_gate): shell downloads bypass "
                 "the references-first gate. Use the WebFetch/WebSearch "
                 "tools (which ask the user) or have the user download "
                 "sources into references/ themselves.")

        # Bash mutation guard — closes the shell bypass around Edit/Write.
        # docxtool mutating commands and raw zip surgery count as writes:
        # the branch gate and protected paths apply to .docx edits too.
        bg = cfg.get("enforcement", {}).get("bash_guard", {})
        mutates = re.search(
            r"\bsed\s+(-\w*\s+)*-i|\btee\b|>>|(?<![<>=])>(?!&)|\bmv\b|"
            r"\brm\b|\bcp\b|\btruncate\b|"
            r"docxtool\.py['\"]?\s+(replace|insert|delete|add-cite|new)\b|"
            r"\bzip\b|\bunzip\s+(-\w*\s+)*-\w*o", cmd)
        if bg.get("enabled", True) and mutates:
            if os.environ.get(pp.get("override_env", "ALLOW_PROTECTED")) != "1":
                for d in pp.get("deny", []):
                    if norm(d).rstrip("/") in cmd:
                        deny(f"BLOCKED by harness (bash_guard): this command "
                             f"can write and mentions protected path '{d}'. "
                             "Protected paths must not be modified — not via "
                             "the shell either.")
            if git.get("enabled", True) and \
                    git.get("require_feature_branch", True) and \
                    branch(root) in prot:
                deny(f"BLOCKED by harness (bash_guard): file-writing shell "
                     f"command while on '{branch(root)}'. Create a feature "
                     "branch first (git checkout -b <prefix><topic>) — the "
                     "branch gate applies to bash edits too.")
        sys.exit(0)

    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        sys.exit(0)
    ap_, rt = os.path.abspath(path), os.path.abspath(root)
    try:
        if os.path.commonpath([ap_, rt]) != rt:
            sys.exit(0)  # outside this project
    except ValueError:
        sys.exit(0)
    rel = relpath(root, path)

    # .docx is a zip of XML — Edit/Write would corrupt it. All docx
    # editing goes through the engine CLI, which self-gates/validates.
    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit") and \
            rel.lower().endswith(".docx") and \
            cfg.get("formats", {}).get("docx", False):
        deny("BLOCKED by harness: .docx is a binary format — Edit/Write "
             "would corrupt it. Use the docx CLI instead:\n"
             "  python3 .harness/engine/docxtool.py cat|show|outline|cites|"
             "replace|insert|delete|add-cite|new ...\n"
             "(replace preserves citation fields via {{field:k}} "
             "placeholders — run 'show' first.)")

    if os.environ.get(pp.get("override_env", "ALLOW_PROTECTED")) != "1":
        for d in pp.get("deny", []):
            if rel.startswith(norm(d)):
                deny(f"BLOCKED by harness (protected_paths.deny): '{d}' must "
                     "not be modified. If the user explicitly asked, rerun "
                     f"with {pp.get('override_env', 'ALLOW_PROTECTED')}=1.")

    exempt = any(rel.startswith(norm(x)) for x in
                 git.get("exempt_paths", []))
    if git.get("enabled", True) and git.get("require_feature_branch", True) \
            and not exempt:
        b = branch(root)
        if b in prot:
            deny(f"BLOCKED by harness (git.require_feature_branch): you are "
                 f"on '{b}'. Run git checkout -b <prefix><topic> first "
                 f"(prefixes: {git.get('branch_prefixes', [])}), then retry.")

    for c in pp.get("confirm", []):
        if rel == norm(c) or rel.startswith(norm(c).rstrip("/") + "/"):
            print(json.dumps({"hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "ask",
                "permissionDecisionReason":
                    f"harness: '{c}' is a confirm-path — verify the user "
                    "explicitly requested this change."}}))
            sys.exit(0)
    sys.exit(0)


if __name__ == "__main__":
    main()
