# Digits functional specification: overview and conventions

This specification is the only input to the clean-room implementation of Digits.
Implementers build the software described here and nothing else. Where a section
says MUST, the behavior is required for functional equivalence; SHOULD marks a
recommended default that may be adjusted with a recorded reason in the
implementation notes.

## Product summary

Digits is a personal workbench for running many GitHub Copilot CLI chats in
parallel on macOS. It has four independently adoptable components:

| Component | Spec file | Summary |
|---|---|---|
| Workbench | `10-workbench.md` | Ten independent environment directories shown as windows of one tmux session, a Copilot CLI extension that publishes per-chat activity state to a live tmux dashboard, a Markdown viewer command, optional terminal shortcut fragments, and a preview-first installer with an ownership receipt |
| Context library | `20-context.md` | A small always-loaded instruction file that routes agents to on-demand topic pages, installed by a preview-first installer that renders paths, writes immutable content-addressed releases, supports hash-bound adoption of an existing file, and rolls back |
| Plugin | `30-plugin-core.md`, `40-plugin-workflows.md` | A Copilot CLI plugin (Agent Plugins 1.0 format) with fourteen skills, their standard-library helpers, and two lifecycle extensions |
| Guards and project files | `50-guards-and-project.md` | Repository source/secret/private-term checks, CI, integration (MCP) examples, and the project documentation set |

## Repository layout (MUST)

```text
README.md  LICENSE            # only these two documents live at the root
requirements-dev.txt  .gitignore
install.py                 # workbench installer (10-workbench.md)
context_install.py         # context installer (20-context.md)
bin/ai-agents  bin/md-view # executables (10-workbench.md)
terminal/                  # tmux and Ghostty fragments (10-workbench.md)
copilot/settings.json      # settings example (10-workbench.md)
copilot/extensions/env-dashboard/   # dashboard extension + tests (10-workbench.md)
claude/hooks/env_dashboard.py  claude/settings.json  # Claude Code hook (10-workbench.md 5a)
context/                   # bootstrap, pages, version.json (20-context.md)
examples/private-bindings/ # binding templates (20-context.md)
plugin/                    # plugin package (30/40)
mcp/                       # integration examples (50)
scripts/                   # guards (50)
tests/                     # Python tests for root modules, guards, context, helpers
docs/                      # build-your-own guide, provenance, release checklist (50)
spec/                      # this specification (read-only for implementers)
.github/workflows/checks.yml  .github/plugin/marketplace.json
.github/CONTRIBUTING.md  .github/SECURITY.md  .github/CODE_OF_CONDUCT.md
docs/provenance.md         # origin, clean-room rebuild record, exclusions
```

## Technology conventions (MUST)

- Python: 3.9-compatible standard library only for runtime code and tests
  (`unittest`). The only development dependency is `detect-secrets==1.5.0`.
- JavaScript: Node.js 22 ES modules (`.mjs`), standard library only, tests with
  `node:test` and `node:assert`.
- Shell helpers: bash, `set -euo pipefail` semantics, must pass `bash -n`.
- No network access, real tmux server, real home directory, real Copilot
  configuration or real external service is touched by any test. Tests use
  temporary directories as `HOME`, isolated tmux sockets (`tmux -L <unique>`),
  and mocked subprocess/service calls.
- Tests MUST be deterministic. Tests that drive tmux or other asynchronous
  processes MUST wait for an observable condition (poll with a bounded timeout,
  for example up to 10 s at 50 ms intervals) instead of relying on fixed sleeps.
  A test that fails intermittently is a defect.
  Assertions that compare two values derived from the wall clock MUST take
  both from a single evaluation (or freeze the clock), never from separate
  reads that can straddle a second boundary.
- Fixtures and examples use neutral placeholder text, never real people's
  names.
- No hardcoded user home paths (`/Users/<name>/`, `/home/<name>/`) anywhere in
  the repository; derive paths from `HOME`/`Path.home()` or parameters.
- Executables (`bin/*`, `plugin/**/*.sh`, Python helpers with a shebang) are
  committed with the executable bit.
- Versions: plugin and marketplace entry `1.0.4`; context library `1.3.0`.
- License: MIT. `LICENSE` holds the standard MIT text; `plugin/plugin.json`
  sets `"license": "MIT"`.
- Names: product "Digits"; plugin name `digits`; marketplace name `digits`;
  command namespace `digits:`; tmux session `ai-agents`; private bindings
  directory `~/.config/digits/context`; state under `~/.local/state/digits/`.

## Environments (MUST)

Ten environment directories directly under the user's home, in this window
order: 1 `left_pinky`, 2 `left_ring`, 3 `left_middle`, 4 `left_pointer`,
5 `left_thumb`, 6 `right_thumb`, 7 `right_pointer`, 8 `right_middle`,
9 `right_ring`, 10 `right_pinky`. Each is an independent directory (users place
separate full clones inside); Digits never clones repositories.

## Global safety principles (MUST, apply to every component)

1. Preview first: every installer prints a plan and writes nothing unless
   `--apply` is given.
2. Ownership: installers record what they wrote (hash, mode) in a private
   receipt and refuse to overwrite or remove files they do not own or that were
   modified after installation.
3. No credentials, tokens, OAuth caches, transcripts, logs, or private profiles
   in the repository; credentials never appear on process argument lists.
4. Skills never send external messages, post human-facing comments, merge,
   deploy, mark PRs ready, or push without the explicit approval described in
   their spec.
5. Organization-specific facts come from command arguments, then the user's
   private bindings, then a single question to the user; never guessed.

## Acceptance

Each component spec ends with numbered acceptance tests. Every listed test MUST
be implemented (names may differ) and pass. The CI workflow in
`50-guards-and-project.md` MUST pass on macOS.
