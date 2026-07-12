#!/usr/bin/env bash
# One-time installer. Run inside the project: bash scripts/install-harness.sh
set -euo pipefail
REPO="$(git rev-parse --show-toplevel)"
cd "$REPO"

echo "==> Pramana installer"
git config core.hooksPath .githooks
chmod +x .githooks/pre-commit .harness/engine/*.py .harness/hooks/*.py
echo "  ✓ git pre-commit gate active (.githooks)"

python3 - <<'PY'
import json, os
with open(".harness/claude-settings-hooks.json") as f:
    hooks = json.load(f)["hooks"]
dst = ".claude/settings.json"
settings = {}
if os.path.exists(dst):
    with open(dst) as f:
        settings = json.load(f)
settings["hooks"] = hooks
os.makedirs(".claude", exist_ok=True)
with open(dst, "w") as f:
    json.dump(settings, f, indent=2); f.write("\n")
print("  ✓ Claude Code hooks -> .claude/settings.json")
PY

# Skills: make the harness's skills discoverable by Claude Code
mkdir -p .claude/skills
cp -R .harness/skills/. .claude/skills/
echo "  ✓ skills -> .claude/skills/"

# IDE integration: build ▶ buttons for IntelliJ and VS Code
mkdir -p .idea/runConfigurations .vscode
cp .harness/ide/idea/runConfigurations/*.xml .idea/runConfigurations/
for f in tasks.json settings.json extensions.json; do
  # don't clobber user-customized VS Code files
  [ -f ".vscode/$f" ] || cp ".harness/ide/vscode/$f" ".vscode/$f"
done
echo "  ✓ IDE run configs -> .idea/runConfigurations + .vscode (reopen IDE)"

# Slash-command wrappers: guarantee /scaffold, /draft, ... work
mkdir -p .claude/commands
for d in .harness/skills/*/; do
  name="$(basename "$d")"
  cat > ".claude/commands/${name}.md" <<WRAP
Invoke the '${name}' skill now: read .harness/skills/${name}/SKILL.md and
follow its activation sequence exactly, starting from step 1. Arguments
given after the command are the intake answers: \$ARGUMENTS
WRAP
done
echo "  ✓ slash commands -> .claude/commands/ ($(ls .harness/skills | tr '\n' ' '))"

python3 .harness/engine/doctor.py \
  || { echo "  ✗ harness is inconsistent — fix doctor errors above"; exit 1; }

python3 .harness/engine/validate.py --check-config \
  || { echo "  ✗ fix the config problems above, then re-run"; exit 1; }

python3 .harness/engine/validate.py --all >/dev/null 2>&1 \
  && echo "  ✓ validator smoke test passed" \
  || echo "  ! validator has findings: python3 .harness/engine/validate.py --all"

echo "==> Done. Tune rules in harness/ (fragments) and harness/rules.d/. Restart Claude Code."
