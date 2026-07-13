# Paramasastra

A hardcoded AI-harness for academic research and journal writing. The idea:
markdown instructions to an AI are *advisory* — the model can drift or
hallucinate past them. This template moves every mechanically-checkable rule
into **code that runs deterministically**, and keeps only judgment rules
(scope, argument quality, source fidelity) in instructions, refreshed into
the AI's context every single turn.

The name is Indonesian, from Sanskrit: **paramasastra** — *parama*
(supreme) + *śāstra* (science, treatise) — the classical term for the
science of language rules. That is what this harness is: the codified
rules of scholarly writing — citations, prose, scope, git, LaTeX —
enforced as law, not suggested as style.

## Design decisions (and why)

| Decision | Choice | Rationale |
|---|---|---|
| Packaging | Template repo | Clone per project; self-contained; projects can diverge freely |
| Rule location | `harness/` config directory (JSONC fragments) | One small file per concern, merged in filename order. Add/change/remove any rule by editing JSON — adding a whole *format* is engine work, but its policy still lives in JSON |
| Formats | LaTeX + Markdown/Quarto + Word (.docx) | Covers manuscripts and research notes; .docx is parsed/edited via the stdlib OOXML engine (no pandoc/python-docx dependency) |
| Citation policy | Offline + online | Offline: cite keys must exist, entries typed, identifier fields required. Online: DOIs verified via Crossref, ISBNs via OpenLibrary, titles fuzzy-matched — a fabricated reference cannot survive CI |
| Coverage | Manuscript only (`manuscript_paths`) | The harness governs the thesis/journal/paper being written; everything else is out of its jurisdiction. An optional per-project `notes_paths` zone can be added where rules warn instead of block |
| Scope guard | Keyword deny-list (warn) + per-turn digest | Mechanical early warning without blocking legitimate related-work mentions |
| Git policy | Fully configurable in JSON | Branch gate, bulk-add ban, commit trailer — each independently switchable |

## Quick start

```bash
# 1. Create a new project from this template
#    (or click "Use this template" on GitHub)
gh repo create my-new-paper --template topahilangharapan/paramasastra --private --clone
cd my-new-paper

# 2. Install enforcement (hooks, skills, slash commands)
bash scripts/install-harness.sh

# 3. Open Claude Code and run /setup: it interviews you once and fills
#    every project-specific value (name, scope, title, author, ...).
#    Manual alternative: edit the config fragments in harness/ yourself:
#    - 00-project.json  -> name, manuscript_paths (where the paper lives)
#    - 50-scope.json    -> scope statement (+ deny_keywords)
#    - 40-citations.json-> bib files, allowed types, required fields
#    - harness/rules.d/ -> drop in any custom rules
```

## Config layout (configurable · maintainable · scalable)

```
harness/                     # merged in filename order; lists concatenate,
├── 00-project.json          #   scalars last-wins; 'key=' replaces a list
├── 10-git.json              # branch gate, bulk-add ban, commit trailer
├── 20-protected-paths.json  # deny / confirm paths
├── 30-prose.json            # knobs; extends presets/prose-anti-ai.json
├── 40-citations.json        # bib policy + online verification
├── 50-scope.json            # scope statement + deny keywords
├── 60-latex.json            # command map, label conventions
├── 65-docx.json             # Word (.docx) manuscripts: citation-field
│                            #   policy, heading contracts, marker style
├── 70-workflow.json         # lifecycle markers + build command
├── 90-enforcement.json      # which checks run where
├── presets/                 # opt-in shared libraries (via "extends")
│   ├── latex-conventions.json # float caption/label integrity, cross-
│   │                          # reference checks (duplicates, unknown
│   │                          # refs, unreferenced floats), ~\ref
│   │                          # hygiene; file-shape contracts for
│   │                          # modular writing declared in 60-latex
│   ├── prose-anti-ai.json   # core forbidden vocabulary/phrases
│   └── human-writing.json   # WP:AISIGNS machine-tell suppression:
│                            #   banned constructions (regex patterns),
│                            #   density-governed suspect words
│                            #   (deterministic per-paragraph/section/
│                            #   file/chapter occurrence limits),
│                            #   md formatting tells
└── rules.d/                 # DROP-IN custom rules — add a file, done
```

Why this scales: each concern is one small file (maintainable); projects
override by adding a later-numbered fragment instead of editing shared ones
(no merge conflicts when you pull template updates); shared lists live in
presets that many projects inherit (update once, propagate); and rule
packs are just files you copy between projects.

Tooling:

```bash
python3 .harness/engine/validate.py --show-config   # effective merged config
python3 .harness/engine/validate.py --check-config  # lint: typos, bad regex/severity
```

A minimal project may instead keep a single `harness.json` at the root —
the loader falls back to it when no `harness/` directory exists.

## The three enforcement layers

1. **Claude Code hooks** (`.harness/hooks/`, wired via `.claude/settings.json`)
   — branch gate, protected paths, bulk-add ban enforced *before* the action
   (including a bash mutation guard: `sed -i`/redirects/`mv`/`rm` cannot
   bypass the gates via the shell); every edited file validated
   *immediately after*, with errors fed straight back to the AI to fix;
   a policy digest generated **from the config** injected into context
   every turn, including **skill auto-activation directives** — when the
   prompt matches `workflow.skill_triggers`, the hook injects a hard
   instruction to invoke that lifecycle skill, so skill activation no
   longer depends on the model noticing; and a **turn-end gate** — the
   Stop hook blocks Claude from finishing a turn while modified manuscript
   files have validator errors.
2. **git pre-commit** (`.githooks/pre-commit`) — steps declared in
   `enforcement.pre_commit.checks`; model-independent, works for any AI or
   human author.
3. **CI** (`.github/workflows/harness.yml`) — full-tree validation, online
   citation verification (cached), protected-path PR gate.

## Adding a rule (no code, ever)

Drop a file into `harness/rules.d/`:

```jsonc
// harness/rules.d/10-style.json
[
  { "id": "no-passive-we", "glob": "paper/**",
    "pattern": "\\bit was decided\\b", "severity": "error",
    "message": "name the actor: 'we decided'" }
]
```

Add an enforcement step by appending its id to
`enforcement.pre_commit.checks` in `harness/90-enforcement.json`
(available: `branch`, `protected_paths`, `validate`, `citations_offline`,
`citations_online`, `doctor`). Verify with `--check-config`.

## Included skills (the writing workflow)

Eight skills ship in `.harness/skills/` (installed into `.claude/skills/` by
the installer). Five form the manuscript lifecycle; markers declared in
`harness/70-workflow.json` carry the handoff between them, and the engine
enforces the contract (E-MARKER: broken pairs are errors; the review gate
runs `--strict-markers` where any leftover marker is an error):

| Skill | Role | Writes prose? |
|---|---|---|
| `setup` | One-time project initialization from the template: interview, rewrite placeholders (project name, scope, title, author), verify | No |
| `scaffold` | Design structure of NEW content: headings, labels, source mapping, @TODO briefs | No — instructions only |
| `draft` | Turn @TODO briefs and @EDIT markers into citation-backed prose | Yes |
| `review` | Read-only audit: mechanical pass (validator + citecheck) + judgment pass, then one-by-one interactive triage | No (mechanical fixes only after triage approval) |
| `revise` | Plan changes to EXISTING content: place @EDIT markers, preserve originals | No — markers only |
| `fix-figure` | Render → visually inspect → fix → re-render loop for diagrams (build command from `harness/70-workflow.json`) | No |
| `defend` | Defense examiner: grills you on your manuscript with grounded questions (3 escalating personas), grades answers, tracks readiness via the coverage engine (`.harness/engine/grillmap.py`) | No — records coverage only |
| `update-harness` | Change the harness itself, doctor-verified | — |

The cycle: **scaffold → draft → review**, then **revise → draft → review**
for every change thereafter. The doctor lints every skill's path
references, so skills cannot go stale silently.

## Updating the harness itself (self-consistency)

Telling the AI "update the harness" is a first-class, safe operation:

- The **`update-harness` skill** (`.harness/skills/update-harness/SKILL.md`,
  installed into `.claude/skills/` by the installer) gives the AI the exact
  procedure: where each kind of change goes (JSON first, engine last),
  which docs to update, and what to verify.
- The **doctor** (`.harness/engine/doctor.py`) makes the outcome hard:
  it verifies config sanity, that every declared enforcement check id is
  implemented, that hook wiring points at real scripts, that **docs
  reference only files that exist** (no stale documentation), that this
  README documents every check id, and that installed `.claude` hooks
  haven't drifted from `.harness/claude-settings-hooks.json`.
- The doctor runs automatically: in the PostToolUse hook whenever a
  harness-surface file is edited (an inconsistent edit is blocked and fed
  back to the AI), in pre-commit via the `doctor` check, in CI, and in the
  installer.

A skill is still an instruction — it can drift like any instruction. The
guarantee comes from the pairing: the skill carries the procedure, the
doctor enforces the postcondition. Run it manually any time:

```bash
python3 .harness/engine/doctor.py
```

## Word manuscripts (.docx)

A `.docx` inside `manuscript_paths` is governed exactly like a `.tex`
file — same prose rules, citation policy, workflow markers, git gates.
Enable with `formats.docx` (on in `harness/65-docx.json`); the engine
parses OOXML with the Python standard library only (no pandoc or
python-docx anywhere).

What is different, because Word is a zip of XML:

- **The "line" is the paragraph.** Validator findings for a `.docx`
  report the 1-based paragraph index in document order. Table
  paragraphs are covered; headers/footers are not governed in v1;
  footnote citations are detected (they report at line 0).
- **Edit/Write are blocked on .docx** (the pre-tool gate redirects).
  All editing goes through the CLI, which gates itself (branch,
  protected paths, Word lock files) and validates the file after every
  mutation — same contract as the per-edit hook:

  ```bash
  python3 .harness/engine/docxtool.py cat paper/ch2.docx        # numbered paragraphs
  python3 .harness/engine/docxtool.py show paper/ch2.docx 7     # one paragraph + fields
  python3 .harness/engine/docxtool.py outline paper/ch2.docx    # heading tree
  python3 .harness/engine/docxtool.py cites paper/ch2.docx      # citation audit
  python3 .harness/engine/docxtool.py replace paper/ch2.docx 7 --text "... {{field:1}} ..."
  python3 .harness/engine/docxtool.py insert paper/ch2.docx 7 --text "@TODO ..." --marker
  python3 .harness/engine/docxtool.py add-cite paper/ch2.docx 7 --key smith2020
  python3 .harness/engine/docxtool.py new paper/ch3.docx --title "Evaluation"
  ```

- **Citations are native fields** — Zotero/Mendeley
  (`ADDIN … CSL_CITATION`) and Word CITATION fields. The validator
  reconstructs each field from its runs (instruction text is routinely
  split across many) and requires it to resolve to a `references.bib`
  entry: DOI first, then ISBN, then fuzzy title
  (`docx.citations.title_match_threshold`). That keeps the whole
  anti-fabrication chain intact — bib entry ⇒ required identifiers ⇒
  shelf file ⇒ online verification in CI. `citecheck.py --docx` prints
  the per-field audit. Plain-text `[@key]` / `[12]` citations warn.
- **The placeholder contract.** `show` renders a paragraph's citation
  fields as `{{field:1}}`, `{{field:2}}`, …; `replace` refuses any
  rewrite that does not carry every placeholder exactly once, then
  splices the original field XML back verbatim — a rewrite mechanically
  cannot drop or duplicate a citation.
- **Markers are visible paragraphs.** Word has no source comments, so
  `@TODO` / `@EDIT` / ORIGINAL–DELETE blocks live in shaded
  `HarnessMarker` paragraphs (style configurable in `docx.markers`) —
  a human opening the file in Word sees unresolved work. Pairing
  integrity (E-MARKER) and the `--strict-markers` delivery gate work
  unchanged.
- **Structure contracts** (`docx.structure`, code `O-STRUCT`): one
  top-level heading per file (the modularity analog), no skipped
  heading levels, optional required-heading regexes. Heading levels are
  resolved from outline levels through the style `basedOn` chain, so
  localized or renamed style names cannot dodge the check.
- **Check ids:** `O-FIELD` (damaged/unparseable citation field),
  `O-CITE` (field resolves to no bib entry), `O-STRUCT` (heading
  contracts).
- **Builds:** point `workflow.build.main` at the `.docx` — the gate
  runs as usual, the validated file is snapshotted into the versioned
  `build/` folder, and a PDF is exported when LibreOffice (`soffice`)
  is installed (`workflow.build.docx_command`); otherwise the snapshot
  is the artifact.
- **Known v1 limits:** tracked changes are read as accepted
  (insertions counted, deletions ignored); footnotes are detected but
  not editable; `docxtool add-cite` synthesizes a Zotero-compatible
  field that Zotero may need to re-link on its next refresh (disable
  with `docx.citations.allow_generated_fields=false` to route new
  citations through `@TODOCITE` markers instead).

## Building the PDF

`bash scripts/build.sh [--strict|--force]` — every build lands in
`build/<YYYY-MM-DD_HHMMSS>_v<N>/` with the PDF, `build.log`, and a
`manifest.json` (git commit, validation status). The builder refuses to
compile a manuscript that fails validation (`--force` overrides loudly
and is recorded). Configure the compile command and main file in
`harness/70-workflow.json` → `workflow.build`.

**IDE ▶ button** (installed by `scripts/install-harness.sh` from
`.harness/ide/`): IntelliJ gets "Build PDF" / "strict" / "force draft"
run configurations in the ▶ dropdown; VS Code gets build tasks
(Cmd/Ctrl+Shift+B runs the gated build) plus LaTeX Workshop recipes so
the extension's build button goes through the harness gate. Reopen the
IDE after installing.

## Manual runs

```bash
python3 .harness/engine/validate.py --all        # everything
python3 .harness/engine/validate.py paper/x.tex  # one file
python3 .harness/engine/citecheck.py --online    # verify DOIs/ISBNs now
```

## What deliberately stays soft

Scope judgment, whether a source really supports a claim, and prose quality
need reasoning — code can't check them. They live in `CLAUDE.md` and in the
per-turn digest, plus (recommended) an LLM-side citation-fidelity review
before submission. Everything else is hard.

## License

[MIT](LICENSE)
