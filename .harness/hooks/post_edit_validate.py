#!/usr/bin/env python3
"""PostToolUse — run the validator on the file Claude just edited.
If the edited file is part of the HARNESS ITSELF (config, engine, hooks,
git gate, CI, docs, skill), additionally run the doctor so an
inconsistent harness update is blocked immediately.
Honours enforcement.post_edit in the harness config.
"""
import json
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ENGINE = os.path.join(os.path.dirname(HERE), "engine")
sys.path.insert(0, ENGINE)
from validate import repo_root, load_config, relpath  # noqa: E402

HARNESS_SURFACE_PREFIXES = ("harness/", ".harness/", ".githooks/",
                            ".github/", "scripts/")
HARNESS_SURFACE_FILES = ("harness.json", "README.md", "CLAUDE.md")


def is_harness_surface(rel):
    return rel.startswith(HARNESS_SURFACE_PREFIXES) or rel in HARNESS_SURFACE_FILES


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
    pe = cfg.get("enforcement", {}).get("post_edit", {})
    if not pe.get("enabled", True):
        sys.exit(0)

    ti = data.get("tool_input", {}) or {}
    path = ti.get("file_path") or ti.get("notebook_path") or ""
    if not path:
        sys.exit(0)

    # Harness self-update? Run the doctor — consistency is blocking.
    if is_harness_surface(relpath(root, path)):
        d = subprocess.run([sys.executable, os.path.join(ENGINE, "doctor.py")],
                           capture_output=True, text=True, timeout=120)
        dout = (d.stdout or "") + (d.stderr or "")
        if d.returncode != 0 and pe.get("block_on_error", True):
            print("You just edited the HARNESS ITSELF and it is now "
                  "inconsistent. Follow the update-harness skill; fix every "
                  "doctor [ERROR] (stale docs included) before proceeding:\n"
                  + dout, file=sys.stderr)
            sys.exit(2)
        if "[WARN]" in dout:
            print("Doctor warnings (non-blocking):\n" + dout)

    r = subprocess.run([sys.executable, os.path.join(ENGINE, "validate.py"),
                        path], capture_output=True, text=True, timeout=120)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 and pe.get("block_on_error", True):
        print("Harness validation FAILED for the file you just edited. "
              "Fix every [ERROR] before proceeding:\n" + out, file=sys.stderr)
        sys.exit(2)
    if "[WARN]" in out or r.returncode != 0:
        print("Harness findings (non-blocking):\n" + out)
    sys.exit(0)


if __name__ == "__main__":
    main()
