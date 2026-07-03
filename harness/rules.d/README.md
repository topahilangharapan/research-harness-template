# rules.d — drop-in custom rules

Add project-specific rules by **dropping a `.json` file here** — nothing
else to edit, no merge conflicts with shared config. Files load in
filename order after all `harness/*.json` fragments.

A file is either an object with `custom_rules`, or a bare list of rules:

```jsonc
// 10-style.json
[
  { "id": "no-etc", "glob": "paper/**",
    "pattern": "\\betc\\.", "severity": "error",
    "message": "avoid 'etc.' in formal prose" },
  { "id": "no-passive-decision", "glob": "paper/**",
    "pattern": "\\bit was decided\\b", "severity": "warn",
    "message": "name the actor: 'we decided'" }
]
```

Fields: `id` (finding code), `glob` (repo-relative path match),
`pattern` (regex, applied per prose line), `severity` (`error|warn|off`),
`message`.

Check your work: `python3 .harness/engine/validate.py --check-config`
