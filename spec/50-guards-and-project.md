# 50 — Guards, CI, integration examples and project documents

Scope of this file: the two repository guards (`scripts/check_repository.py`,
`scripts/check_secrets.py`) and their tests, the CI workflow, the plugin
marketplace manifest, `requirements-dev.txt`, `.gitignore`, the MCP integration
examples under `mcp/`, and the project documentation set (`README.md`,
`CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`, `PROVENANCE.md`,
`docs/build-your-own.md`, `docs/open-source-release-checklist.md`).

Conventions from `00-overview.md` apply (MUST/SHOULD, Python 3.9 standard
library, no network in tests, no hardcoded home paths). Behavior of the
workbench, context installer and plugin is owned by `10-workbench.md`,
`20-context.md`, `30-plugin-core.md` and `40-plugin-workflows.md`; this file
only references it where the documents must describe it.

A note on self-reference: this specification lives in `spec/`, which is part of
the repository and therefore scanned by the guards described below. Any example
in tests or documents that needs a machine home path MUST be assembled at run
time (string concatenation) or written with a placeholder such as `<name>`, so
that the committed text never contains a literal match. The same applies to
fake secrets in tests.

---

> **Layout amendment (supersedes paths below).** Only `README.md` and `LICENSE`
> (standard MIT text) live at the repository root. `CONTRIBUTING.md`,
> `SECURITY.md` and `CODE_OF_CONDUCT.md` live in `.github/`. Provenance lives in
> `docs/provenance.md`, which also contains the clean-room rebuild record
> (formerly `CLEAN_ROOM.md`) as a "How it was rebuilt" section. Wherever this
> document names the old root paths, apply these locations and adjust relative
> links accordingly. Release checklist blocker 1 (license) is done: MIT.
> The provenance acknowledgements credit Ken Crowell by name (replacing the
> placeholder), and the README states the project is released under MIT.

## 1. Shared concept: the index must equal the working tree

Both guards inspect the files a contributor is about to commit. Because a
contributor could stage one version of a file and then overwrite the working
copy with a cleaner version, each guard first proves that the staged content
and the working-tree content of tracked files are identical.

### 1.1 Contract (MUST)

- The check runs `git diff --quiet --no-ext-diff --no-textconv --` with the
  repository root as working directory, capturing (not displaying) its output.
  This compares the index with the working tree for tracked paths only;
  untracked files are irrelevant to this step, and differences between `HEAD`
  and the index are allowed.
- Exit status 0: the check passes silently.
- Exit status 1 (there are unstaged modifications, including a tracked file
  deleted from the working tree): the check fails with a *mismatch* error whose
  message begins with the phrase `Staged files differ` and tells the user to
  review the diff and stage the content they intend before re-running.
  (Recommended full wording, freely rephrasable after the required opening:
  "Staged files differ from the working tree; inspect `git diff` and stage what
  you mean to commit, then rerun the checks.")
- Any other non-zero status (for example the directory is not inside a Git
  repository, or Git itself errors) is a *comparison failure*, never treated as
  a pass. Its message MUST contain `Could not compare` and state that checks
  stopped (recommended: "Could not compare the Git index with the working tree;
  checks stopped.").
- The two failure kinds are distinguishable by the caller (the reference uses
  a value-type error for the mismatch and a runtime-type error for the
  comparison failure; acceptance test 5 requires the comparison failure to be
  a distinct, catchable kind carrying the `Could not compare` text).
- Implemented once, in `scripts/check_repository.py`, as a function taking the
  repository root as a parameter (SHOULD be named `require_index_match(root)`),
  and reused by `scripts/check_secrets.py`.

### 1.2 Module import contract (MUST)

- Tests run from the repository root with `python -m unittest discover -s tests`
  and import the guards as `scripts.check_repository` and
  `scripts.check_secrets` (namespace package or `scripts/__init__.py`; either is
  fine).
- `scripts/check_secrets.py` MUST obtain the index check from the repository
  guard both when imported as part of the `scripts` package and when executed
  directly as `python scripts/check_secrets.py` (the script's own directory is
  then on the import path).
- Each module exposes a module-level repository-root value (SHOULD be named
  `ROOT`) computed as the parent of the `scripts/` directory, which tests
  replace with a temporary directory. Every filesystem and Git operation in the
  module MUST resolve paths from that value at call time.
- Each module exposes `main()` that returns an integer exit status (0 pass,
  1 fail) instead of exiting; the `__main__` block exits with that value.
- The repository guard exposes a per-file inspection function (SHOULD be named
  `inspect_file(relative_path)`) that takes a path relative to the root and
  returns a list of human-readable error strings (empty list means clean).
- The repository guard exposes the constants `PRIVATE_TERMS_ENV`
  (value `DIGITS_PRIVATE_TERMS`) and `DEFAULT_PRIVATE_TERMS` (the path
  `.config/digits/private-terms.txt`, relative to the home directory).
- Both guards are run with an interpreter (`python scripts/<name>.py`); they
  SHOULD start with a `python3` shebang. If they do carry a shebang, the
  executable-bit rule in `00-overview.md` applies.

---

## 2. `scripts/check_repository.py` — structure, path, JSON and private-term guard

### 2.1 Purpose

Rejects private or runtime artifacts, machine-specific home paths, malformed
JSON, symlinks, non-UTF-8 files, a missing root README and (optionally)
user-listed private terms, across every file that would be part of a source
snapshot.

### 2.2 Command line

- Invocation: `python scripts/check_repository.py`. No arguments, no flags.
- Environment: `DIGITS_PRIVATE_TERMS` (optional) and `HOME` (used to locate
  the default terms file).
- Exit 0 on success with a single summary line on standard output.
- Exit 1 on any failure, with diagnostics on standard error. Nothing is
  printed to standard output on failure.

### 2.3 Order of operations (MUST)

1. **Index check** (section 1). On mismatch or comparison failure, print the
   error message to stderr and return 1. No files are inspected.
2. **Resolve the private-terms file** (section 2.7). A configuration error
   (explicit path missing, file unreadable or not valid UTF-8) prints the error
   to stderr and returns 1. No files are inspected.
3. **Enumerate files** (section 2.4).
4. For each file in sorted order: run the per-file inspection (2.5), then, if
   at least one private term is loaded and the path is not a symlink, the
   private-term scan (2.8).
5. **Root README requirement**: if `README.md` is not a regular file at the
   repository root (checked on the filesystem, independent of Git listing),
   add the failure `README.md: missing project README`.
6. If any failure was collected, print all of them to stderr, one per line, in
   collection order (files in sorted path order, each file's inspection errors
   before its private-term findings, the README failure last), and return 1.
7. Otherwise print the success summary (2.9) to stdout and return 0.

### 2.4 File set enumeration (MUST)

- The candidate set is produced by
  `git ls-files --cached --others --exclude-standard -z` run at the root:
  every tracked (index) path plus every untracked path that is **not** ignored
  by `.gitignore`, the repository exclude file, or the global excludes file.
- Paths are split on NUL, empty entries dropped, de-duplicated, and sorted.
  Paths are kept relative to the root and are what every message prints.
- If this Git command fails, the guard fails with a non-zero exit (an uncaught
  error is acceptable; it MUST NOT report success).
- Ignored files (for example a local `.venv/` or `__pycache__/`) are therefore
  never inspected by this guard.

### 2.5 Per-file inspection (MUST)

Each inspection error is reported as `<relative path>: <message>`.

1. **Symlink rejection.** If the path is a symbolic link (to anything,
   including a missing target or a directory), the only error returned is a
   message saying symlinks are not accepted in a source snapshot. No further
   checks run for that path, and the private-term scan skips it.
2. **Private/generated/binary artifact.** One error (message conveying
   "private, generated, or binary artifact is not allowed") if **any** of these
   holds (all comparisons case-sensitive):
   - the final path component exactly equals a **private name**:
     `.DS_Store`, `.env`, `fish_variables`, `mcp-config.json`,
     `permissions-config.json`, `profiles.yaml`, `profiles.yml`;
   - the final component starts with `.env.` (so `.env.local` and
     `.env.example` are both rejected);
   - the final suffix (text from the last dot of the final component,
     inclusive; a name whose only dot is its leading character, such as
     `.pem` or `.gitignore`, has no suffix) is a **private suffix**: `.bak`, `.db`, `.key`, `.log`, `.mp4`,
     `.p12`, `.pem`, `.pfx`, `.png`, `.sqlite`, `.sqlite3`, `.vsix`, `.xlsx`,
     `.zip`;
   - **any** path component (directory names and the file name itself) equals a
     **private directory name**: `.local`, `logs`, `mcp-oauth-config`,
     `node_modules`, `restart`, `resurrect`, `session-state`,
     `sidebar-sessions-state`;
   - the final component contains a **backup marker**: a literal dot, then
     `bak` or `backup`, followed by a hyphen, a dot, or the end of the name
     (pattern `\.(bak|backup)([-.]|$)`, searched anywhere in the name).
     Examples rejected: `saved.bak-20261020`, `notes.backup`,
     `config.bak.json`, `x.backup-1`. Examples accepted: `bakery.md`,
     `a.bakfile`, `backup.md` (no leading dot before `backup`).
   - Exact-name matching means `mcp-config.example.json` is **not** a private
     name and is accepted.
3. **UTF-8 requirement.** The file is read as text, decoded strictly as UTF-8.
   If reading fails (decode error, or an OS error such as the path being a
   directory or a submodule entry), return the errors gathered so far plus a
   message that the file must be readable UTF-8 source, and stop inspecting
   this file (no home-path or JSON check).
4. **Home-path detection.** Add the error `hardcoded user home path` if the
   decoded text contains, anywhere (not only at line start, any line), the
   sequence: `/`, then exactly `Users` or `home` (case-sensitive), then `/`,
   then one or more characters drawn only from ASCII letters, digits, `_`,
   `.`, `-`, then `/`. Constant pattern: `/(?:Users|home)/[A-Za-z0-9_.-]+/`.
   Consequences: a bare `/Users/` is fine; a user segment without a trailing
   slash is not matched; `~/...` and `$HOME/...` are fine; placeholders such as
   `/Users/<name>/` are fine (angle brackets are outside the character class);
   a path such as `/opt/` + `home/x/` *is* matched because the search is not
   anchored. One error per file regardless of how many matches.
5. **JSON validation.** Only when the final suffix is exactly `.json`: parse
   the whole text as JSON (standard-library parser semantics). On failure add
   `invalid JSON at line <N>` where N is the parser-reported 1-based line of
   the error. An empty `.json` file is invalid. Other extensions (`.jsonl`,
   `.json5`) are not parsed.
6. Multiple errors for one file are all reported (for example a private-named
   JSON file that also fails to parse yields two lines).

### 2.6 Text decoding note

The reference relies on the platform default encoding being UTF-8 (true on
macOS and the CI runner). The clean implementation MUST decode explicitly as
UTF-8 so the outcome does not depend on locale.

### 2.7 Private-terms file resolution (MUST)

- If `DIGITS_PRIVATE_TERMS` is set to a **non-empty** value: expand a leading
  `~`, and if the result is not an existing regular file, fail with a message
  that names `DIGITS_PRIVATE_TERMS`, says it does not point to a readable file,
  and includes the resolved path. Exit 1.
- An empty `DIGITS_PRIVATE_TERMS` is treated exactly like unset.
- If unset: use `<home>/.config/digits/private-terms.txt`, where `<home>` is the
  current user's home directory as derived from `HOME`. If that file does not
  exist, the guard is **skipped** (not a failure).
- Loading: read the file as UTF-8 text; number lines from 1; strip leading and
  trailing whitespace from each line; ignore lines that are then empty or begin
  with `#`; every remaining line is one term, compared case-insensitively
  (Unicode case folding). Each term is remembered with its **line number in the
  terms file**. A read or decode error is a configuration failure (exit 1).
  Error messages MUST NOT include any term.
- A terms file that exists but contains only comments and blank lines loads
  zero terms; the guard then counts as "checked 0 terms" and no scan happens.

### 2.8 Private-term scan (MUST)

- Applies to every enumerated path that is not a symlink, only when at least
  one term is loaded. A file that cannot be read as UTF-8 is silently skipped
  by this scan (its inspection error already reports it).
- For each line of the file (1-based numbering, standard line splitting), case
  fold the line and, for each term in terms-file order, if the folded term is a
  **substring** of the folded line (no word boundaries), add one finding:
  `<relative path>:<line>: private term #<N>` where N is the term's line number
  in the terms file (comments and blank lines still count toward numbering).
- Several terms on one line give several findings; one term occurring twice on
  one line gives one finding for that line.
- Findings never contain the term itself, the matched text, or the line
  content. No other output path (success summary, errors) may reveal a term.

### 2.9 Success summary (MUST)

One line on stdout reporting that structure, JSON and path checks passed, the
number of enumerated files, and the private-terms guard outcome:

- terms file resolved: "private-terms guard checked K terms" (K may be 0);
- no terms file: a phrase containing `guard skipped` (recommended:
  "private-terms guard skipped (no terms file)").

Recommended full form:
`Repository structure/JSON/path checks passed (<N> files); <guard outcome>.`

---

## 3. `scripts/check_secrets.py` — offline secret scan

### 3.1 Command line and flow (MUST)

- Invocation: `python scripts/check_secrets.py`. No arguments.
- Step 1: the index check (section 1). Failure prints its message to stderr
  and returns 1 without scanning.
- Step 2: run the external scanner as a subprocess, with the repository root as
  working directory, capturing stdout as text:
  `detect-secrets scan --no-verify --all-files --exclude-files <regex>`
  - `detect-secrets` is found on `PATH` (not via `python -m`);
  - `--no-verify`: the scanner MUST NOT contact any service to verify findings
    (no network);
  - `--all-files`: walk every file under the root, not only Git-tracked ones
    (so untracked and even ignored files are scanned, minus exclusions);
  - `--exclude-files` value: `(^|/)(\.git|\.venv|__pycache__|node_modules)(/|$)`
    — excludes the Git directory, a local virtual environment, bytecode
    caches and Node dependency trees at any depth;
  - no baseline file is used or written.
- If the executable cannot be found: stderr message saying `detect-secrets` is
  missing and should be installed from `requirements-dev.txt` in an isolated
  environment; return 1. Never report success.
- If the scanner exits non-zero: stderr message saying the scanner failed and
  that no passing result is claimed; return 1.
- Otherwise parse stdout as JSON and read its `results` object (map of file
  path → list of finding objects, each with at least `line_number` and
  `type`).
- If there is at least one finding: print to stderr one line per finding,
  `<path>:<line_number>: <type>` (iterate files in the scanner's order and
  findings in list order), and return 1.
- No findings: print to stdout a line saying the secret scan passed and that
  manual review is still required; return 0.

### 3.2 Output safety (MUST)

- Neither the secret value, any portion of it, nor the scanner's
  `hashed_secret` field is ever printed. Only path, line number and detector
  type appear.
- The scanner's raw stdout/stderr are captured, never echoed.

---

## 4. CI workflow — `.github/workflows/checks.yml`

| Field | Value |
|---|---|
| `name` | `Source checks` |
| Triggers | `pull_request` (any branch, default activity types) and `push` restricted to branch `main` |
| `permissions` | `contents: read` only (workflow-level) |
| Jobs | one job, id `source` |
| `runs-on` | `macos-latest` |
| Secrets / env | none |

Steps, in this exact order:

1. `actions/checkout@v4`
2. `actions/setup-python@v5` with `python-version: "3.12"`
3. `actions/setup-node@v4` with `node-version: "22"`
4. Ensure tmux: if `brew list tmux` (output silenced) fails, run
   `brew install tmux`.
5. `python -m pip install -r requirements-dev.txt`
6. `python scripts/check_repository.py`
7. `python scripts/check_secrets.py`
8. `python -m unittest discover -s tests`
9. `python -m unittest discover -s plugin/skills/inter-env -p 'test_*.py'`
10. Syntax-check every standup-update shell helper: for each
    `plugin/skills/standup-update/*.sh`, run `bash -n` on it.
11. `node --check copilot/extensions/env-dashboard/extension.mjs`
12. `node --test copilot/extensions/env-dashboard/*.test.mjs`
13. For each plugin lifecycle extension entry
    `plugin/com.github.copilot/extensions/*/extension.mjs`, run `node --check`.
14. `node --test plugin/com.github.copilot/extensions/*/*.test.mjs`

Notes:

- Paths in steps 9–14 are those fixed by `10-workbench.md`, `30-plugin-core.md`
  and `40-plugin-workflows.md`; if those specs place a file elsewhere, the CI
  globs MUST follow them so that no step silently matches nothing.
- The guards run before any test so that bytecode caches created by tests do
  not exist yet (they are ignored anyway).
- On CI no private-terms file exists, so the private-terms guard reports
  "skipped"; this is expected.
- Each `run` step is a single shell command; a failing command fails the job.

---

## 5. Plugin marketplace manifest — `.github/plugin/marketplace.json`

Valid JSON object with exactly these keys:

| Key path | Value |
|---|---|
| `name` | `"digits"` |
| `owner.name` | `"Digits maintainers"` |
| `plugins` | array with exactly one object |
| `plugins[0].name` | `"digits"` |
| `plugins[0].description` | one sentence, written fresh, saying the plugin provides approval-guarded Copilot CLI workflows covering: PR review handling, rebases, investigations, standup drafting, coordination across several environments, and context improvement that proposes before it changes anything |
| `plugins[0].version` | `"1.0.0"` — MUST equal `version` in the plugin manifest (`30-plugin-core.md`); a test there enforces it |
| `plugins[0].source` | `"./plugin"` |

Install commands that depend on this file: `copilot plugin marketplace add
<path-to-repo>` then `copilot plugin install digits@digits`.

---

## 6. `requirements-dev.txt` and `.gitignore`

### 6.1 `requirements-dev.txt` (MUST)

Exactly one requirement: `detect-secrets==1.5.0`. No other dependencies.

### 6.2 `.gitignore` (MUST contain all of these entries)

| Group | Entries |
|---|---|
| OS / editor noise | `.DS_Store` |
| Python | `__pycache__/`, `*.pyc`, `.venv/` |
| Node | `node_modules/` |
| Environment files | `.env`, `.env.*` |
| Machine-local overrides | `*.local.json`, `*.local.yml`, `*.local.yaml` |
| Key material | `*.pem`, `*.key`, `*.p12`, `*.pfx` |
| Backups, logs, databases | `*.bak`, `*.log`, `*.db`, `*.db-shm`, `*.db-wal` |
| Host runtime state | `session-state/`, `mcp-oauth-config/`, `resurrect/`, `.local/` |

Interaction to be aware of: an ignored file is invisible to the repository
guard (section 2.4) but still scanned by the secret guard (`--all-files`)
unless it is under an excluded directory.

---

## 7. MCP integration examples — `mcp/`

### 7.1 `mcp/mcp-config.example.json` (MUST)

A valid JSON object with one top-level key `mcpServers` containing exactly four
entries, in this order:

| Server key | `type` | Connection keys | `tools` |
|---|---|---|---|
| `atlassian` | `http` | `url`: `https://mcp.atlassian.com/v2/mcp` | `["*"]` |
| `slack` | `http` | `url`: `https://mcp.slack.com/mcp` | `["*"]` |
| `example-remote` | `http` | `url`: `https://mcp.example.invalid/mcp`; `headers`: `{ "Authorization": "__SET_IN_LOCAL_CONFIG__" }` | `["__LIST_REVIEWED_READ_ONLY_TOOLS__"]` |
| `example-local` | `local` | `command`: `"__REVIEWED_LOCAL_COMMAND__"`; `args`: `["__REVIEWED_PACKAGE_AT_PINNED_VERSION__"]`; `env`: `{ "EXAMPLE_API_TOKEN": "__SET_IN_LOCAL_CONFIG__" }` | `["__LIST_REVIEWED_READ_ONLY_TOOLS__"]` |

Placeholder convention: upper-case words joined by underscores, wrapped in
double underscores on each side. Placeholders are inert strings, not an
interpolation syntax. The file contains no real secret, account, host or
tenant, passes both guards (its name is not a private name; the placeholders
must not trip the secret scanner — verify by running it), and is never meant
to be loaded unchanged.

### 7.2 `mcp/README.md` — sections in order and required points

**Title**: a heading identifying the file as the MCP integration recipes.

**Opening paragraph** must convey:
- What follows is guidance for setting integrations up — not a credential
  export and not a configuration to switch on directly.
- A link to `mcp-config.example.json`, described as an illustration of the
  structure Copilot CLI expects, still full of placeholders, which must never be
  loaded without editing.
- Readers enable only the services they actually need and must leave any
  unrelated entries in their personal client file untouched.

**Ground rules** — a bulleted list; each bullet opens with a bold summary.
Required points (any order):
- *Secrets live outside Git.* Store tokens in the operating-system keychain,
  in a password manager, or in environment variables supplied when the client
  starts; choose OAuth whenever both service and client offer it; any local
  file holding a secret sits outside the repository and is readable only by
  its owner (e.g. mode 600).
- *Working MCP files are never committed.* Name the things that must not be
  copied into any repository: the user file `~/.copilot/mcp-config.json`,
  OAuth cache directories like `~/.copilot/mcp-oauth-config/`, credential
  headers belonging to plugins, and backup copies of configuration. State that
  the repository guard refuses the usual filenames and the secret guard looks
  for credential-shaped strings, yet a human review is still needed.
- *Only your own access.* Never reuse values taken from a colleague's account;
  while troubleshooting, never print or display a secret.
- *Prove it with something harmless.* The first check of each integration is
  a tiny read-only call on data the user can already see; setup involves no
  writing, posting or deleting.
- *An empty tool list proves nothing.* Clients may load tool lists lazily or
  defer them, so a list can look empty; look at the client's MCP status and
  run discovery before deciding the server is broken or absent.
- *A denial is a stopping point.* When authentication, permissions or the
  connection fail, halt and say which access or setup step is missing; never
  try a different account, role, token or path to get past it.
- *Valid syntax is only step one.* Keep four milestones distinct: the file
  parses; tools are discovered; the user is authenticated; an authorized call
  succeeds. CI here never calls live services.

**Client configuration** must state:
- Copilot CLI's per-user server list is `~/.copilot/mcp-config.json`; extra
  servers can come from workspace-level files or the `--additional-mcp-config`
  flag.
- All of these files share one top-level key, `mcpServers`.
- Hosted servers declare `type` `http` (or `sse`), a `url`, and optionally
  `headers`. Servers launched on the machine declare `type` `local`, plus
  `command`, `args`, `env` and, if needed, `cwd`.
- `tools` restricts which tools are exposed; when omitted every tool is exposed
  (`["*"]`). For servers that can modify data, list only tools you reviewed.
- Other clients, VS Code being the named example, have their own formats;
  dropping a CLI file into them achieves nothing.
- Pick server names that do not clash with servers already built in or
  provided by plugins.
- The example holds two real hosted endpoints published by their vendors and
  two deliberately fake entries that mark where local values belong. A table
  with columns Entry | Source | Authentication | Harmless verification:

  | Entry | Source (link and endpoint) | Authentication | Harmless check |
  |---|---|---|---|
  | `atlassian` | vendor repository `https://github.com/atlassian/atlassian-mcp-server`; endpoint `https://mcp.atlassian.com/v2/mcp` | OAuth per user inside the client; choose a site the user is entitled to | list the tools, then fetch a single issue the user can already view |
  | `slack` | vendor docs `https://docs.slack.dev/ai/slack-mcp-server/`; endpoint `https://mcp.slack.com/mcp` | OAuth via an app the workspace allows, following the vendor's client instructions | list the tools, then read one channel the user is a member of |
  | `example-remote` | fake host under `example.invalid` | header value supplied only in local configuration | none (dash) |
  | `example-local` | fake command and package | environment value supplied only in local configuration | none (dash) |

- No entry is needed for GitHub because Copilot CLI already bundles its MCP
  server.
- When a vendor distributes a plugin carrying its own MCP setup, install that
  plugin from the vendor's supported source instead of copying it here.
- Strings such as `__SET_IN_LOCAL_CONFIG__` are not expanded by anything;
  substitute real values using whatever the client supports, or delete the
  entry.
- Locally launched packages are pinned to a version someone reviewed; never
  "latest".

**Recipe template**
- One sentence: copy the block below to document another integration; if it
  names organization details, keep the filled-in copy in private bindings.
- A fenced Markdown block containing a level-3 heading placeholder for the
  service, followed by seven bold-labelled bullets with angle-bracket
  placeholders, in this order:
  1. *Source and transport* — vendor URL or a pinned `package@version`; one of
     `http`, `sse`, `local`.
  2. *Official documentation* — link to the vendor's up-to-date setup page.
  3. *Authentication* — OAuth, keychain-held token, or the name of an
     environment variable; where the secret is kept locally; who grants
     access.
  4. *Local configuration* — server name, the `tools` allowlist, any settings
     that are not secret.
  5. *Harmless verification* — a single read-only request against visible
     data.
  6. *Failure handling* — how a denial shows up and whom to ask (never swap
     credentials).
  7. *Write capabilities* — tools able to modify data and the approval that
     guards them.

**References** — three links: the Copilot CLI page on adding MCP servers
(`https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-mcp-servers`),
the Copilot CLI page on finding and installing plugins
(`https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-finding-installing`),
and `https://modelcontextprotocol.io/`.

---

## 8. `README.md`

The README is the entry point for users. The headings below are REQUIRED, in
this order. `CONTRIBUTING.md` links to the anchors `#make-it-yours` and
`#verification`, so those two headings must read exactly "Make it yours" and
"Verification". All wording is new; every listed point must appear.

### 8.1 `# Digits` — introduction
- One-sentence pitch: Digits helps someone keep many Copilot CLI agent
  conversations running side by side without losing track of any.
- Bulleted list of the four separable parts, each with a bold name:
  - **Dashboard**: one tmux session holding ten independent environments named
    after fingers (`left_pinky` to `right_pinky`); a live activity view per
    chat with timers; switch by clicking; a shortcut that jumps to whichever
    chat needs attention.
  - **Plugin**: workflow skills for Copilot CLI covering PR reviews,
    rebasing, investigation, standup drafting and coordination between
    environments, each gated by explicit approval and defaulting to dry runs.
  - **Context library**: a short bootstrap file that is always loaded, holding
    a route table, plus Markdown topic pages pulled in only on demand
    (progressive disclosure); its installer previews first, keeps immutable
    snapshots and can roll back.
  - **Integration recipes**: MCP configuration examples with no credentials,
    plus a template for documenting new integrations.
- Users may take any subset. Digits does not image workstations, provision
  repositories, or impose organizational policy.
- Point to `docs/build-your-own.md` for readers adapting the approach to their
  own tools.

### 8.2 `## Status`
- The project is pre-release.
- In bold: there is no license yet, so nobody is granted any rights until one
  is added.
- Link to `docs/open-source-release-checklist.md`.

### 8.3 `## Requirements`
Bulleted:
- macOS — the only platform tested.
- tmux; Python 3.9+; Node.js; GitHub Copilot CLI (link
  `https://docs.github.com/en/copilot/how-tos/copilot-cli`).
- The login shell the launcher opens in every environment, as fixed by
  `10-workbench.md` (fish when installed, otherwise `$SHELL`, so fish is
  listed as optional with that reason).
- Optional extras: Ghostty (`https://ghostty.org/`) for the keyboard
  shortcuts; Visual Studio Code for the `md-view` viewer.

Then prose:
- Copilot itself is authenticated separately. GitHub or MCP sign-in matters
  only for workflows that call those services.
- Because the dashboard extension uses experimental Copilot SDK APIs, users
  must enable experimental mode with `/settings experimental on`. Tested CLI
  versions: 1.0.100 to 1.0.105; anything else should be validated first.

### 8.4 `## Quick start`
- Intro: run everything from the repository root; each installer only
  previews unless `--apply` is passed.
- `### Dashboard` — code block, three commands with trailing comments:
  `python3 install.py` (dry run), `python3 install.py --apply` (perform
  it), and `~/.local/bin/ai-agents` (start or reattach). Following prose, per
  `10-workbench.md`: what gets installed is five runtime files — the launcher,
  `md-view`, the tmux configuration for the dashboard, and the extension's
  `extension.mjs` plus `state.mjs` — and any absent environment directory is
  created. Explicitly list what it leaves alone: no cloning, no chat start, no
  authentication, no edits to Copilot settings, Ghostty, MCP config, or the
  user's global tmux config.
- `### Plugin` — code block: `copilot plugin marketplace add /path/to/digits`
  then `copilot plugin install digits@digits`. Prose: `plugin/README.md`
  covers updating and setting up individual skills; certain skills only become
  useful after local, non-secret bindings exist.
- `### Context library` — code block: `python3 context_install.py` (dry run), then
  `python3 context_install.py --apply` (perform it), then
  `python3 context_install.py --rollback` (dry run of returning to the
  prior snapshot). Prose, per `20-context.md`: taking over an instruction file the
  user already has requires adoption bound to its hash; receipts, backups and
  bindings never leave the machine; link `context/README.md`.
- `### Integrations` — link `mcp/README.md`, noting that it keeps secrets out
  of Git and explains verifying each service with a harmless read.

### 8.5 `## Dashboard`
Everything here restates `10-workbench.md` for users and must agree with it.
- Opening: the launcher starts the managed tmux session `ai-agents`, or
  reattaches if it exists.
- Two-column-pair table mapping windows to environments: 1–5 on the left
  pair, 6–10 on the right, order per `00-overview.md`.
- Facts about environments: each is its own directory in the home folder;
  users place distinct clones in them (never shared worktrees) and launch
  Copilot by hand where wanted.
- Facts about the launcher: existing panes and the current window survive a
  rerun; a window name that conflicts causes a refusal; chats are never
  restarted. Closing the terminal only detaches — the session keeps running.
  After rebooting, environments come back as new shells; conversations are not
  restored.
- `### States` — a State | Meaning table with rows READY, WORKING, SUBAGENTS,
  WATCHING, NEEDS YOU, ERROR, a combined `COPILOT / UNKNOWN` row (nothing
  published yet vs. tracking failed), YOUR TURN, WAITING; meanings as in
  `10-workbench.md`. Prose after the table:
  - Priority: pending input and errors win over any background wait. Services
    started detached are not counted as watched shells.
  - Timers: WORKING, SUBAGENTS and WATCHING display time since the run began;
    YOUR TURN displays the turn's length and its finishing clock time (sample
    `4m12s @09:46`); WAITING displays time elapsed since finishing.
  - Waiting reasons: right-click a YOUR TURN row to type a reason; submitting
    an empty one clears it; resuming work also clears it. It is a personal
    note, not a scheduling feature.
  - Mechanics: the view redraws every second with tmux's own format strings;
    state comes from lifecycle events plus SDK snapshots rather than polling;
    if tracking breaks, the entry reads UNKNOWN and retries with a capped
    backoff.
- `### Shortcuts`:
  - Clicking an entry switches to that environment; a **hotkeys** button in
    the top-right corner lists every shortcut and runs the chosen one.
  - Two optional fragments, linked: `terminal/ghostty-keybindings.conf`
    (Ghostty) and `terminal/ai-agents-shortcuts.tmux.conf` (tmux).
  - A Shortcut | Action table: Cmd+1…Cmd+9 and Cmd+0 pick windows 1–10;
    Cmd+Shift+] and Cmd+Shift+[ go forward/back with wrap-around; Cmd+; returns
    to the previous window; Cmd+` jumps to the next chat wanting attention —
    NEEDS YOU before YOUR TURN, WAITING never; Cmd+Shift+M shows that chat's
    most recent session Markdown in `md-view`.
  - `md-view` renders into a separate VS Code instance with its own profile at
    `~/Library/Application Support/digits-markdown-viewer`; the user's normal
    editor windows are never touched.
  - Adoption is manual because the installer edits neither Ghostty nor the
    global tmux file: merge the Ghostty bindings; place the tmux fragment at
    `~/.tmux/ai-agents-shortcuts.conf`; add the line
    `source-file ~/.tmux/ai-agents-shortcuts.conf` to `~/.tmux.conf`.
  - Cautions: the Ghostty bindings override Ghostty's tab shortcuts, its
    Cmd+0 font-size reset, and macOS's Cmd+` window cycling. The tmux fragment
    occupies `user-keys[180]` through `user-keys[194]` for the whole server,
    so check nothing else uses them; only the managed session responds.
- `### Updating and removal`:
  - Ownership: a pre-existing file the installer did not create is refused,
    even if byte-identical. The receipt at
    `~/.local/state/digits/dashboard.json` stores each file's hash and mode and
    the directories created. Re-running apply only replaces owned files that
    are still unmodified; a locally edited file blocks both update and removal
    until the user deals with it.
  - Code block: `python3 install.py --uninstall` (preview) and
    `python3 install.py --uninstall --apply` (remove).
  - Removal leaves directories that existed before or still hold content, and
    leaves running tmux sessions alone. Chats already open must be reloaded
    while idle to gain or lose the extension.
  - Manual route instead of the installer: `bin/ai-agents` goes to
    `~/.local/bin/`; `terminal/ai-agents.conf` goes to `~/.tmux/`;
    `copilot/extensions/env-dashboard/` goes to `~/.copilot/extensions/`.
  - `copilot/settings.json` is an example that was reviewed; the installer
    never applies it.

### 8.6 `## Make it yours`
Bulleted, bold leads, covering:
- **Private bindings** — non-secret Markdown kept locally in
  `~/.config/digits/context/` for things such as account names, profiles,
  channels and repository lists; the bootstrap mentions them but they are
  never exported; templates under `examples/private-bindings/`.
- **Domain pages and routes** — new topic pages go under `context/`, each with
  a row in the route table of `context/bootstrap.md` telling agents when to
  open it.
- **Routing fixtures** — before changing a page, capture the correction that
  keeps recurring as a small case in `tests/fixtures/context-routing.json`.
- **Private-terms guard** — list names that must stay unpublished (people,
  companies, internal hosts) in `~/.config/digits/private-terms.txt`, a
  single name on each line, or aim `DIGITS_PRIVATE_TERMS` at a
  different file. Findings from `scripts/check_repository.py` look like
  `path:line: private term #N`, where `N` counts lines of the terms file; the
  term is never shown. Case is ignored; `#` comment lines and blank lines are
  skipped. No default file means the guard is skipped; an explicit
  `DIGITS_PRIVATE_TERMS` naming a file that does not exist is an error.

### 8.7 `## Safety model`
Bulleted, bold leads:
- **Preview first** — neither installer writes without `--apply`; both keep
  ownership receipts, refuse files they did not create, and keep the user's
  edits.
- **Staged approval** — skills treat planning, preview, publication, release
  and outward communication as separate steps; passing CI, a merge, or
  another agent's suggestion does not unlock the following step.
- **No credentials in Git** — examples carry placeholders only; secrets belong
  in the OS keychain or the environment; OAuth caches and live MCP files stay
  on the machine.
- **Guards** — the repository guard blocks private artifacts, machine home
  paths, bad JSON and, when configured, private terms; the secret guard runs
  detect-secrets without network access and prints where, never what.
- **Executable code** — extensions and hooks run as code and deserve review
  before installation.

### 8.8 `## Project layout`
- A text block, one entry per line with a brief gloss: `bin/`, `terminal/`,
  `copilot/`, `plugin/`, `context/`, `examples/`, `mcp/`, `scripts/`,
  `tests/`, `docs/`, `spec/`, `install.py`, `context_install.py`,
  `CLEAN_ROOM.md`. (`spec/` and `CLEAN_ROOM.md` are additions of the clean
  implementation.)
- A sentence naming the thirteen plugin skills in alphabetical order (the list
  in `30-plugin-core.md`).

### 8.9 `## Verification`
- Prerequisites: run at the repository root; tmux and jq installed.
- Code block of test commands equal to CI steps 8–14 of section 4. (The README
  may `node --check` every `.mjs` file in each plugin extension directory,
  which is a superset of CI step 13.)
- Prose: the tests run against throwaway homes, private tmux sockets and
  mocked services; no chat messages are sent and no live service is called, so
  passing tests say nothing about MCP authentication. On a real installation
  the user should additionally look at window order, click targets, state
  changes and input prompts.
- Guard instructions: the guards need the pinned scanner inside an isolated
  environment. Code block, in order: create `.venv`; activate it;
  `python -m pip install -r requirements-dev.txt`; `git add -A` with a comment
  reminding the user that the index must hold exactly the planned commit;
  `python scripts/check_repository.py`; `python scripts/check_secrets.py`.
- Closing prose: index and working tree must match for either guard to run;
  untracked files that are not ignored are covered too; every finding gets a
  real review, and blanket exemptions are not the answer.

### 8.10 `## Contributing and security`
- Links: `CONTRIBUTING.md`, `SECURITY.md`, `CODE_OF_CONDUCT.md`.
- `PROVENANCE.md` tells where the package came from and what was left out on
  purpose; `CLEAN_ROOM.md` records the clean-room process.

---

## 9. `CONTRIBUTING.md`

Required sections, in order:

1. **Title and welcome** — thanks people for helping; notes the project is
   pre-release and unlicensed; contributions get accepted only after a license
   is picked.
2. **Proposing a change** — numbered steps:
   1. For anything sizeable, start with an issue describing the problem or
      the workflow to be supported.
   2. Each pull request does one thing; refactoring and behavior changes go in
      separate PRs.
   3. The PR description says what users will notice and which approval or
      safety boundary, if any, the change affects.
3. **Keep it generic** — opening line: Digits provides mechanisms, never a
   particular organization's configuration. Bullets:
   - Company names, accounts, channels, repository lists and profiles belong
     in private bindings (`~/.config/digits/context/`; templates in
     `examples/private-bindings/`) and never in this repository.
   - Examples use only `example-org`, `example.com`, `example.invalid`.
   - Do not commit credentials, tokens, MCP files containing secrets, chat
     transcripts or session state.
   - Anyone whose fork started life as a private harness should run the
     private-terms guard locally (link `README.md#make-it-yours`).
4. **Tests** — add a small number of targeted tests, ideally inside an
   existing test file, for whatever behavior is added or fixed; each must fail
   when the change is reverted. Tests only ever use temporary home
   directories, isolated tmux sockets and mocked services; they never reach
   live services or real user configuration. Before opening a PR, run the
   checks in `README.md#verification`, including both guards against the
   staged changes.
5. **Commits** — Conventional Commits 1.0.0
   (`https://www.conventionalcommits.org/en/v1.0.0/`), types `feat:`, `fix:`,
   `docs:`, `test:`, `refactor:`, `chore:`; brief imperative subject; mark a
   breaking change with `!` or a `BREAKING CHANGE:` footer.
6. **Code of conduct** — contributors are bound by `CODE_OF_CONDUCT.md`.

## 10. `SECURITY.md`

Required sections, in order:

1. **Title** — security policy.
2. **Reporting a vulnerability**:
   - Bold instruction: security problems must not be filed as public issues.
   - Preferred channel: GitHub's private vulnerability reporting (the "Report a
     vulnerability" button under the Security tab), linked to
     `https://docs.github.com/en/code-security/security-advisories/guidance-on-reporting-and-writing-information-about-vulnerabilities/privately-reporting-a-security-vulnerability`;
     fallback: reach the maintainers privately.
   - A report should name the component, the version or commit, steps to
     reproduce and the impact seen.
   - Bold instruction: real secrets, tokens or personal data must never be
     pasted into a report — describe or redact them.
   - Maintainers intend to acknowledge quickly and to coordinate disclosure
     after a fix ships.
3. **Scope and expectations** — bullets:
   - The dashboard extension, plugin extensions and skill helpers are
     executable and run with the user's own permissions; read them before
     installing and read updates before reloading.
   - Installers default to preview and will not overwrite files they do not
     own; any way around those protections counts as in scope.
   - Committed credentials are never acceptable; anyone who spots one in the
     tree or in history should report privately so it can be rotated and
     purged.
   - Problems in third-party services, MCP servers or Copilot CLI go to the
     respective vendor.

## 11. `CODE_OF_CONDUCT.md`

1. **Title** — Code of Conduct.
2. Adoption by reference of Contributor Covenant 2.1, linked to
   `https://www.contributor-covenant.org/version/2/1/code_of_conduct/`;
   it binds contributors and maintainers in all project spaces.
3. **Reporting** — unacceptable behavior goes to the maintainers at a bold,
   obviously unset placeholder contact of the form
   `<ENFORCEMENT CONTACT — to be set before publication>`; reports get prompt,
   confidential handling under the Covenant's enforcement guidelines.

## 12. `PROVENANCE.md` (new content for the clean implementation)

Required sections, in order:

1. **Title** — Provenance.
2. **Origin**:
   - The idea grew out of one engineer's private Copilot CLI setup — a tmux
     dashboard, some workflow skills and an accumulating body of instructions —
     refined over several private iterations and later generalized.
   - Bold statement that this repository is a clean-room implementation: one
     team examined how the earlier private version behaved and wrote `spec/`;
     a second team that never had access to that code produced everything else
     from `spec/` only. Link `CLEAN_ROOM.md` for the full process (author rules,
     contamination check, isolated implementation, verification).
   - It is not an export, and not a copy of anyone's home directory or
     dotfiles. Nothing organization-specific is present — no company or
     personal names, internal hosts, repositories, channels or defaults —
     only generic placeholders (e.g. `example-org`) and the private-bindings
     pattern.
3. **Design ideas carried forward** (as concepts only) — bullets:
   - every environment gets its own full clone; no shared worktrees;
   - the dashboard reacts to Copilot lifecycle events instead of polling;
   - installers preview before writing, keep receipts of what they own, store
     immutable snapshots and support rollback;
   - context is disclosed progressively: a small bootstrap plus route table,
     with pages read only when relevant;
   - approval comes in stages, each granted separately — passing CI or a merge
     never implies the next;
   - helpers are deterministic and tested with mocks, leaving judgment to
     humans.
4. **Deliberately excluded** — a lead sentence saying none of these exist in
   the repository and none may be added, then bullets:
   - credentials of any kind: tokens, OAuth caches, keychain items, MCP
     configuration containing secrets;
   - personal profiles for databases, clouds or tools, and certificate bundles;
   - transcripts, session state, logs, any live runtime state;
   - organizational inventories: repository lists, account/role grants,
     channels, ticket metadata, schedules, staff directories;
   - proxies, token helpers or service tooling specific to one company;
   - scheduled jobs; paths tied to one machine.
   - Closing sentence: users keep their own equivalents as private bindings in
     `~/.config/digits/context/`; installers never export them.
5. **Acknowledgements — to be confirmed before publication** (this exact
   heading). A blockquote opening with a bold "Placeholder." label saying:
   - the ideas behind several workflow skills (investigation framing, the
     per-claim challenge pass, assessing review feedback, triaging draft PRs,
     rebasing PRs, updating shared workflows) came from patterns seen in a
     different engineer's personal harness — no name given;
   - prior to publication, maintainers must secure that engineer's consent and
     preferred credit wording, or take the derived material out;
   - finishing or deleting this section is an item in
     `docs/open-source-release-checklist.md` (linked).

## 13. `docs/build-your-own.md` — section-by-section outline

Audience: an engineer, or an agent working on their behalf, who wants a
harness in the Digits style tailored to their own organization. All prose is
new.

**Title** "Build your own Digits". Intro paragraphs convey: this is a practical
guide for that reader; Digits began as a single engineer's workbench at one
company; this repository retains the mechanisms and strips company detail; the
guide describes each mechanism, its purpose, and how to recreate or adapt it
for a different stack, host or team — without adopting another person's
habits wholesale.

### 13.1 Section "1. What Digits is"
- Framing: a pattern, not a product; five layers, each usable alone.
- Table with columns Layer | Problem it solves | Generic implementation here:

  | Layer | Problem | Implementation in this repository |
  |---|---|---|
  | Workbench | with many concurrent chats it is unclear which one is waiting on you | ten separate full clones (`~/left_thumb` … `~/right_pinky`) as windows of one tmux session; an extension reports each chat's state (examples: WORKING, NEEDS YOU, YOUR TURN) to a dashboard with timers, clickable entries and an attention hotkey |
  | Context harness | agents lose conventions; long instruction files get skimmed or crowd out the actual task | a short always-loaded bootstrap (boundaries + route table) and topic pages fetched by intent; installed as immutable content-addressed releases supporting hash-bound adoption and rollback |
  | Private bindings | shared source must not carry the real names of accounts, profiles or channels, nor repository lists | non-secret Markdown local to the machine under `~/.config/digits/context/`; the bootstrap points to it; never exported |
  | Workflow plugin | multi-step chores (review feedback, rebases, investigations, standups, coordination across chats) are done unevenly or unsafely | skills with approval gates and dry-run defaults, helpers using only the standard library with mocked tests, and two lifecycle extensions (refresh in place; finish and reset) |
  | Learning loop | the same correction keeps coming back | each correction turns into a routing fixture, then an edit to a topic, then checks, then a reviewed install; a `self-improve` command that proposes before changing anything reviews recent chats using a private cursor |

- Three unifying principles (numbered, bold leads):
  1. *Approval comes in stages and is never assumed* — planning, preview,
     publication, release, rollout, recovery and external messages each need
     their own permission; none is implied by passing CI, a merge, an older
     handoff or a recommendation from another agent.
  2. *Load little, route the rest* — only the bootstrap is automatic; anything
     else is reached through intent or symptom routes (examples: "wrong
     role", "missing release bump", "empty MCP search") leading to the page
     required before a specific consequential step.
  3. *Prose is backed by deterministic checks* — fixtures, link and metadata
     tests, installer ownership tests, the three guards, and mocked helper
     tests make guidance regressible; a keyword test is a guard, not proof of
     how a model behaves.

### 13.2 Section "2. Decide what you actually need"
- Suggest the agent interviews the user (or the user self-answers) and that
  answers are stored in private bindings, never in shared source.
- Table with columns Question | Why it matters | Where the answer goes:

  | Question | Why | Destination |
  |---|---|---|
  | Which host or hosts: Copilot CLI, Claude Code, Codex, something else? | fixes the instruction-file location, skill/plugin format and extension or hook API | installer constants and the host adapter (guide section 6) |
  | How many chats run concurrently? | decides whether the workbench pays off | the launcher's list of environments |
  | Which outside systems do agents use (code host, tracker, chat, observability, warehouse, cloud)? | every one needs a recipe, a route, and rules for access denial | `context/integrations/` plus bindings |
  | What may never happen without the user (merges, deployments, posts humans will read, production queries, credential changes)? | these turn into bootstrap boundaries and skill gates | `context/bootstrap.md` and the individual skills |
  | What is expensive or hazardous to get wrong in this domain? | each one gets its own domain page naming the step it must precede | `context/domains/*.md` |
  | Which identifiers must stay private — tenants, accounts, people, channels, the repository list? | they go into bindings and into the private-terms denylist | `~/.config/digits/` |
  | Which recurring workflows burn time? | skill candidates — begin with one or two | `plugin/skills/` |

- Advice to start small: most of the benefit comes from a solid bootstrap, a
  couple of domain pages and a single guarded skill.

### 13.3 Section "3. Build plan for an agent"
Preamble: phases run strictly in order, each gated by its acceptance check;
live configuration is never written without a preview and explicit consent.
Each phase is a subsection with bulleted actions and a bold "Accept when"
sentence:

- **Phase 0 — inventory and boundaries.** Actions: read existing instruction
  files, skills and settings without changing them; build a preservation map
  (two columns: earlier guidance, where it now lives) so nothing disappears
  unnoticed; list approval boundaries and private identifiers gathered in
  guide section 2. *Accept when:* the user has signed off on both the
  boundary list and the map.
- **Phase 1 — bootstrap.** Actions: write `context/bootstrap.md` in three
  parts, aiming at 1,000–2,000 words and treating 3,000 as a red flag.
  (a) Rules that always apply: staged approval, the line between human and bot
  interactions, behavior on access denial (stop, name what is missing, no
  credential switching), tool discovery (schemas are never guessed), checking
  environment and repository identity, verifying real outcomes rather than
  proxies, and communication style. (b) A route table with columns intent or
  symptom | page | before, keyed on what the user said or what failed rather
  than file names. (c) A handful of reminders that are both frequent and
  expensive to forget. *Accept when:* a trivial unrelated request (such as
  renaming a variable) would trigger no topic-page read, as shown by Phase 4
  fixtures.
- **Phase 2 — topic pages.** Actions: one subject per page, fewer than 200
  lines; a metadata header shown in a fenced example with the title and five
  markers — `Use when`, `Scope`, `Sources`, `Reviewed` (`YYYY-MM-DD`),
  `Recheck`; decision procedure first, reasoning after; examples only if they
  help and then varied; live inventories kept in bindings or a private fork
  while the shared repo ships a template with invented rows. *Accept when:*
  every page carries all five markers, all relative links resolve, and each
  page is reachable from the bootstrap.
- **Phase 3 — installer.** Actions: no symlinks, no hand copying. Preview by
  default with `--apply` to write. Substitute absolute paths for `{{HOME}}`, `{{CONTEXT_ROOT}}`
  and `{{PRIVATE_ROOT}}`, and convert every relative link to a `file:///` URL
  carrying an absolute path, aborting on unknown placeholders or dead links before
  anything is written. Content-addressed immutable releases, so chats that are
  already running keep working links. A private ownership receipt with hashes
  and modes; unowned files refused; adopting a hand-written instruction file
  requires the exact hash shown in preview (`--adopt-sha256`). Rollback
  restores the previous entry and retains older releases while anything still
  points at them. Out of scope: settings, MCP auth, terminal config,
  repositories, schedules. Mention that `context_install.py` and its tests
  already do all this and should be reused. *Accept when:* tests in temporary
  homes cover a preview that writes nothing, hash-bound adoption, update,
  rollback, refusal on local edits, refusal of symlinks, and hostile receipt
  paths.
- **Phase 4 — routing fixtures and evaluation.** Actions: create
  `tests/fixtures/context-routing.json` with de-identified prompts, the pages
  they should reach and the expected behavior; note that the static test only
  shows routes exist and are mentioned. For behavioral evaluation: isolate
  each run (throwaway home and workspace; read-only tools; no MCP, writes,
  shell or outbound messages); run both model families several times with
  held-out paraphrases; judge by observed file reads and attempted actions,
  not by the model's own claims; include controls — unrelated tasks that
  should load nothing extra and denied-access cases that should halt rather
  than retry with other credentials. *Accept when:* controls pass and every
  routed case opens the expected page before the gated action.
- **Phase 5 — private bindings.** Actions: create `~/.config/digits/context/`
  with files such as `tool-and-repo-bindings.md` and
  `data-warehouse-bindings.md` modeled on `examples/private-bindings/`; record
  non-secret facts with their provenance (which profile, warehouse size,
  channel, mandatory ticket fields); credentials never; a missing binding
  pauses only the action that needs it. *Accept when:* neither installer nor
  source reads, copies or exports these files, and a run of the shared source
  with `DIGITS_PRIVATE_TERMS` set reports no private terms.
- **Phase 6 — skills.** Actions: choose the one or two biggest time sinks.
  Per skill: frontmatter `name` identical to its directory and a
  `description` that names its triggers; settings resolved from explicit
  arguments, then bindings, then a single batched question — identifiers are
  looked up live, never guessed; side effects gated by dry-run or plan-first
  defaults, the exact outbound text shown before sending, state such as the PR
  head rechecked before every write, and force-pushes pinned to the recorded
  previous head; helpers limited to the standard library, locating files
  relative to the installed skill, tested with mocks; non-goals written down
  (examples: no automatic merges, no replies to humans without approval, no
  creating schedules). *Accept when:* mocked helper tests pass and a plugin
  install into a temporary host home yields exactly one registration per
  skill.
- **Phase 7 — workbench (optional).** Actions: only worth it for heavy
  parallel use; one full clone per environment because worktrees share refs
  and invite collisions; each chat's state written into a tmux option on its
  pane by code running inside the host (extension or event hooks), never
  scraped from the screen; lifecycle
  events drive state while polling only refreshes the display; an idempotent
  launcher that keeps panes, refuses clashing windows and never restarts
  chats; a preview-first installer with a receipt and clean uninstall.
  *Accept when:* tmux tests on an isolated socket cover window order, click
  targets and all state transitions.
- **Phase 8 — learning loop.** Procedure when the user corrects the agent:
  (1) extract the lasting, non-sensitive lesson and discard the transcript;
  (2) add a focused fixture; (3) change the smallest existing topic, merging
  into an existing rule rather than adding a global one; (4) run checks,
  preview, apply, then preview again expecting zero changes; (5) report the
  source edit, the install, publication and the refresh of other chats as
  four separate results. Periodic review uses a proposal-first command and a
  private "reviewed-through" cursor that moves only after the user approves
  the proposals (or explicitly approves making none) and validation passes.

### 13.4 Section "4. What the generic open-source version looks like"
- A text tree with one-line comments covering: README (quick start per
  component, safety model); the four policy documents; `bin/`; `terminal/`;
  `copilot/`; `context/`; `examples/private-bindings`; `plugin/` (Agent
  Plugins 1.0 package); `mcp/`; `scripts/` (guards); `tests/`; `docs/`; the
  two installers; `.github/` (CI and the `digits` marketplace manifest); plus
  `spec/` and `CLEAN_ROOM.md`.
- **Kept, generalized, removed** — framed as the difference from the private
  predecessor. Table columns Area | Kept as is | Generalized | Removed:
  - *Workbench*: kept — launcher, states, timers, hotkeys, md-view;
    generalized — the receipt location (`~/.local/state/digits/`); removed —
    nothing.
  - *Context*: kept — loader contract, installer, metadata markers, fixtures;
    generalized — bootstrap boundaries and the pages on GitHub delivery,
    engineering decisions, continuity, IaC lifecycle, writing and MCP
    diagnosis, one generic data-warehouse domain, an issue-tracker page, and a
    repository map reduced to a template; removed — organizational account
    families, tenants, warehouse names, repository inventories, the list of
    review bots, release-dispatch steps, summaries of controlled documents.
  - *Plugin*: kept — the nine skills that needed no organization data
    (assess-and-address, challenge-pass, done, draft-pr-sweep, inter-env,
    investigate, rebase-pr, self-improve, summarize); generalized — the three
    skills that now read channel, reactions and organizations from arguments
    or bindings (request-review, review-reactions, update-shared-workflows),
    and the standup drafter, renamed `standup-update`, with a configurable
    tracker site; removed — hardcoded channels, tracker site IDs, people,
    organization product names.
  - *Integrations*: kept — the recipe principles; generalized — an example
    config without credentials; removed — one company's auth proxy and token
    helper.
  - *Guards*: kept — the source and secret checks; generalized — an added,
    optional private-terms guard driven by a local denylist; removed —
    nothing.
- **Configuration model** — table Kind of value | Where it lives:
  - generic rules and mechanisms → the shared repository;
  - facts specific to one organization, such as required fields, channels,
    repositories or accounts → private bindings, or `context/domains` in a
    private fork;
  - in-flight work: approvals, receipts, the PR head being acted on, task
    state → kept in that session's artifacts, never in long-term memory or
    source;
  - credentials → the OS keychain or the host's built-in authentication —
    never Markdown and never command-line arguments.
- **Versioning** — bullets: the plugin and marketplace versions change in
  lockstep, enforced by a test; the context library is versioned separately in
  `context/version.json` and bumped with each reviewed context change; because
  installs are content-addressed, a bump cannot break chats already running,
  and idle chats pick up new instructions, skills and extensions through the
  `digits-refresh` extension.

### 13.5 Section "5. Customization recipes"
- *New domain* (worked example: deploying to Kubernetes): create
  `context/domains/kubernetes.md`, give it all five metadata markers, name the
  step it must precede
  (e.g. before pushing manifests to a shared cluster); add its route row; add
  two or three fixtures, at least one negative; keep cluster names and
  contexts in bindings.
- *New skill*: `plugin/skills/<name>/SKILL.md` plus a standard-library helper
  and a mocked test; hook it into CI; raise the plugin and marketplace
  versions together.
- *New integration*: a recipe in `mcp/README.md` saying where the credential
  lives, which harmless read verifies it, and how a denial looks; then a row
  for access denial on the MCP diagnosis page.
- *Different tracker or chat product*: update the bindings and the recipe
  only; the skills are already phrased in terms of a configured channel and an
  issue tracker.

### 13.6 Section "6. Porting to another agent host"
- Opening: the design does not depend on one host, but how instructions and
  skills load varies and keeps changing; check current official documentation
  for each host before trusting a path or format.
- A three-column table — aspect; how the Copilot CLI reference does it; what
  to check on other hosts (always against their current docs). Rows:
  - always-loaded user instructions: `~/.copilot/copilot-instructions.md`
    (doc `https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions`)
    vs. Claude Code's memory files with their import
    syntax (`https://code.claude.com/docs/en/memory`)
    and Codex's `AGENTS.md` discovery
    (`https://developers.openai.com/codex/guides/agents-md`);
  - skills loaded when needed: `SKILL.md` files in a plugin vs. the skill
    mechanisms of Claude Code and Codex
    (`https://developers.openai.com/codex/skills`);
  - lifecycle hooks/extensions: the experimental extension SDK used by the
    dashboard, refresh and done vs. whatever hooks a host offers — with no
    equivalent, leave out the dashboard layer;
  - packaging: an Agent Plugins 1.0 marketplace vs. the host's own plugin
    format, or plain directories and an installer.
- Closing advice: a port touches only the installer's target path and the
  packaging; bootstrap, pages, bindings, fixtures and guards carry over
  unchanged; one prompt text serves every model family — no per-model forks.

### 13.7 Section "7. Anti-patterns"
Bullets, each a mistake to avoid:
- growing the global instruction file with every correction;
- pulling in all topic pages eagerly through `@` imports or discovery globs;
- putting account IDs, channel names or people in shared source, even as
  "examples";
- reading an empty tool search as evidence that an integration is gone, or
  retrying a refused action under other credentials;
- allowing a skill to take the next consequential step (posting, merging,
  deploying, marking ready) just because the previous one went well;
- symlinking live configuration into a repository, or exporting a dump of a
  home directory;
- mandating multi-agent fan-out, or making productivity claims nobody can
  verify, instead of review proportionate to risk;
- declaring success on the strength of a keyword test, a route the model
  reported about itself, or a CI job that was skipped.

### 13.8 Section "8. Publishing your own"
- Link the release checklist and summarize it in four bullets: license plus
  employer sign-off; attribution and consent for borrowed material; publication
  from a fresh history and never from an internal branch's history; all guards
  run with a personal private-terms list, with executable extensions and hooks
  reviewed as code.

## 14. `docs/open-source-release-checklist.md`

Required sections, in order:

1. **Title and intro** — for use before this repository or anything derived
   from it is published beyond the organization maintaining it; until all
   blockers are closed it stays internal or private.
2. **Blockers** — a table with columns `#` | Item | Owner | Status. Six rows,
   every status initially "Open" (row 1 adds that no license has been chosen):

   | # | Item (paraphrase) | Owner |
   |---|---|---|
   | 1 | Pick a license, add a `LICENSE` file, and update the README status and package metadata | maintainer together with legal |
   | 2 | Get the employer's approval for open-source release, covering IP assignment, the contribution policy, and a trademark/name check on "Digits" | maintainer |
   | 3 | Confirm consent and attribution for the workflow-skill ideas taken from another engineer's personal harness, and finish the `PROVENANCE.md` placeholder | maintainer with the original author |
   | 4 | Publish into a new repository from fresh history (the clean-room history that starts at the specification commit, or a single new squashed commit); internal main history and other internal branches are never pushed publicly | maintainer |
   | 5 | Run all guards with the maintainer's private-terms list and confirm they are clean on the precise commit to be published | maintainer |
   | 6 | Have someone independent review all executable code — both installers, the launcher, the shell helpers, the dashboard extension, and the plugin extensions `session-done` and `digits-refresh` — paying particular attention to the wide unattended approvals granted by the standup-update scheduled runner `run-scheduled.sh` | reviewer |

3. **Verification on the exact commit to publish** — a code block running, in
   order: virtual-environment creation and activation; installation of
   `requirements-dev.txt`; the repository guard with `DIGITS_PRIVATE_TERMS`
   pointing at a placeholder path (`/path/to/private-terms.txt`); the secret
   guard; both unittest discoveries (CI steps 8–9); `bash -n` over the
   standup-update shell helpers; a single `node --test` covering both the
   dashboard and plugin extension test globs. Then prose: a term list can miss
   things, so also search by hand for internal host names, organization names,
   people and internal links; examine `git log` and the tags of the repository
   that will be published.
4. **Recommended before announcing** — bullets with bold leads:
   - *Experimental dependencies*: README says the dashboard and extensions rely
     on experimental extension APIs of Copilot CLI and lists the CLI versions
     verified.
   - *Maintenance*: add `CODEOWNERS`; turn on private vulnerability reporting
     and security advisories; fill in the code-of-conduct enforcement contact.
   - *Public CI*: confirm CI runs on public hosted runners and needs neither
     internal secrets nor self-hosted machines.
   - *Fresh-account walkthrough*: using only the README, install the dashboard,
     plugin and context into a brand-new user account and uninstall them.
   - *Clean-room record*: `CLEAN_ROOM.md` is complete and the similarity-scan
     result is recorded (new for the clean implementation).
   - *Optional*: screenshots or a short recording of the dashboard.

---

## 15. Acceptance tests

Unless stated otherwise, every test runs in a fresh temporary directory, with
the guard module's root value pointed at it, `HOME` pointed at a separate
temporary directory, no network, and stdout/stderr captured. "Inspect" means
calling the per-file inspection on a file written at that relative path.

### Repository guard — per-file inspection (from the reference repository tests)

1. **Private configuration names are rejected.** Given a file
   `mcp-config.json` containing `{}`, when inspected, then at least one error is
   returned. Given `session-state/transcript.json` containing `{}`, then at
   least one error. Given `saved.bak-20261020` containing `{}`, then at least
   one error.
2. **Machine home paths are rejected.** Given `settings.md` whose content is
   the run-time concatenation of `/` + `Users` + `/` + `fixture` + `/.copilot`,
   when inspected, then at least one error is returned (the test source itself
   must not contain the literal path).
3. **Sanitized examples stay valid; broken JSON fails.** Given
   `mcp-config.example.json` containing an object whose `env` maps
   `LOCAL_VALUE` to `__LOCAL__`, when inspected, then no errors. Given
   `broken.json` containing `{`, then at least one error.

### Index agreement (both guards)

4. **Staged content hidden by a cleaner working copy is rejected by both
   guards.** Given a new Git repository where `fixture.txt` was staged with a
   line containing a home path (built at run time) and then overwritten in the
   working tree with harmless text, when the repository guard's `main()` and
   then the secret guard's `main()` are run with root at that repository, then
   each returns 1 and its stderr contains `Staged files differ`. When the file
   is then staged again, the index check on that root completes without
   error.
5. **A failed comparison is not a match.** Given an empty temporary directory
   that is not a Git repository, when the index check is called on it, then it
   raises the comparison-failure kind whose message contains `Could not
   compare`.

### Private-terms guard (from the reference repository tests)

Fixture for 6–9: a fresh Git repository (nothing staged) containing untracked
`README.md` (`# Fixture`) and `notes.md` with line 1 `# Release notes` and line
2 `Shipped by Glimmerfax today`.

6. **A match reports location only.** Given the default terms file
   (`<HOME>/.config/digits/private-terms.txt`) with lines `# private names`,
   blank, `glimmerfax`, and `DIGITS_PRIVATE_TERMS` unset, when the repository
   guard runs, then it returns 1, combined output contains
   `notes.md:2: private term #3`, and the case-folded output does not contain
   `glimmerfax`.
7. **Comments and blank lines are not terms.** Given a terms file with lines
   `# Release notes`, blank, and whitespace-only, when the guard runs, then it
   returns 0 (the comment text appears verbatim in `notes.md` but is not a
   term; the whitespace-only line does not match everything).
8. **Missing default terms file skips the guard.** Given no terms file and
   `DIGITS_PRIVATE_TERMS` unset, when the guard runs, then it returns 0 and the
   output contains `guard skipped`.
9. **Explicit missing terms file fails.** Given `DIGITS_PRIVATE_TERMS` set to a
   non-existent file path, when the guard runs, then it returns 1 and the
   output contains `DIGITS_PRIVATE_TERMS`.

### Secret guard (from the reference secret-check tests)

10. **A missing scanner is not success.** Given the index check stubbed to
    pass and launching the scanner raising "executable not found", when the
    secret guard runs, then it returns 1.
11. **Network verification is disabled.** Given the index check stubbed and
    the subprocess runner stubbed to return exit 0 with stdout
    `{"results": {}}`, when the secret guard runs, then it returns 0 and the
    argument list passed to the runner contains `--no-verify`.
12. **A real finding is reported without its value** (runs only when
    `detect-secrets` is on `PATH`; otherwise skipped with a reason pointing to
    `requirements-dev.txt`). Given a new Git repository with staged `bad.py`
    assigning a random 64-hex-character string to a variable named `password`,
    when the secret guard runs on it, then it returns 1, stderr contains
    `bad.py`, and stderr does not contain the random value.

### Additional edge cases (MUST also be implemented)

13. **Symlink short-circuit.** Given a symlink `link.json` pointing to a file
    with invalid JSON, when inspected, then exactly one error is returned and
    it concerns symlinks; and with a terms file whose term appears in the
    target, the guard reports no private-term finding for `link.json`.
14. **Backup-name pattern.** `notes.backup`, `config.bak.json` and
    `x.backup-1` are rejected; `bakery.md` and `backup.md` are accepted.
15. **Environment files.** `.env` and `.env.example` are rejected;
    `env.md` is accepted.
16. **Private directory anywhere in the path.** `docs/logs/readme.md` and
    `a/node_modules/b.js` are rejected.
17. **Private suffixes are case-sensitive and last-suffix only.**
    `image.png` is rejected; `archive.zip.md` is accepted.
18. **Non-UTF-8 content.** A `.md` file containing the byte `0xFF` yields the
    UTF-8 error and no home-path or JSON error.
19. **Home-path boundaries.** Text containing `/Users/<name>/`, `~/x`, or a
    bare `/home/` is accepted; text containing `/home/` + `ci-runner/` (built at
    run time) is rejected.
20. **JSON line number.** A `.json` file whose second line is malformed yields
    `invalid JSON at line 2`.
21. **Untracked non-ignored files are inspected; ignored files are not.** In a
    Git repository with `.gitignore` listing `*.log`, an untracked `out.log`
    is absent from the failure output, while an untracked `keys.pem` (not
    ignored by that repository's rules) appears in it.
22. **Missing root README.** A Git repository with only `a.md` fails with
    `README.md: missing project README`.
23. **Term numbering and multiplicity.** Terms file lines: `# c`, `alpha`,
    blank, `Beta`. A repository file whose line 1 is `ALPHA and beta` yields
    two findings for line 1, `#2` then `#4`; neither term text appears anywhere
    in the output.
24. **Substring matching.** A term `fax` matches a line containing
    `Glimmerfax`.
25. **Zero terms.** A terms file with only comments makes the success summary
    report that the guard checked 0 terms (exit 0).
26. **Empty override equals unset.** `DIGITS_PRIVATE_TERMS` set to the empty
    string behaves like unset (default file used or guard skipped).
27. **Explicit override with `~`.** `DIGITS_PRIVATE_TERMS=~/terms.txt`
    resolves against `HOME` and is used.
28. **Index check precedes everything.** With an unstaged modification and a
    missing explicit terms file, the repository guard reports the index
    mismatch (not the terms error) and returns 1.
29. **Scanner failure is not success.** With the subprocess runner stubbed to
    exit non-zero, the secret guard returns 1 and prints a message that no
    passing result is claimed.
30. **Finding format.** With the runner stubbed to return one finding
    (`path` `x.py`, `line_number` 3, `type` `Secret Keyword`, plus a
    `hashed_secret`), stderr is exactly the line `x.py:3: Secret Keyword` and
    does not contain the hash.
31. **Scanner arguments.** The stubbed runner receives `detect-secrets`,
    `scan`, `--no-verify`, `--all-files`, `--exclude-files` and the exclusion
    regex from section 3.1, with the repository root as working directory.
32. **Success messages.** Secret guard success prints a line to stdout saying
    the scan passed and manual review is still required; repository guard
    success prints the file count.
33. **Repository self-check.** On a clean checkout of the implementation, both
    guards exit 0 (`check_repository.py` with no terms file reports
    "skipped").
34. **Example config validity.** `mcp/mcp-config.example.json` parses, has
    exactly the four server keys of section 7.1 with the listed `type` values,
    and contains no value other than the public URLs, `["*"]`, and
    double-underscore placeholders.
35. **Marketplace manifest.** `.github/plugin/marketplace.json` has the keys
    and values in section 5, and its plugin version equals the plugin
    manifest's version.
36. **CI workflow.** `.github/workflows/checks.yml` declares the triggers,
    read-only permissions, `macos-latest` runner, toolchain versions and the 14
    steps of section 4 in order, and passes on GitHub-hosted macOS.
37. **Documentation links.** Every relative link in the documents of sections
    8–14 resolves to an existing file, and the anchors `#make-it-yours` and
    `#verification` exist in `README.md`.
