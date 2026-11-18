# Digits

Digits lets you keep a large number of GitHub Copilot CLI agent conversations
going in parallel without ever losing sight of one of them.

It comes in four parts that you can adopt separately:

- **Dashboard**: a single tmux session with ten independent environments, each
  named after a finger (`left_pinky` through `right_pinky`). A live activity
  view shows what every chat is doing and for how long, a click switches to
  that environment, and one shortcut jumps straight to whichever chat is
  waiting for you.
- **Plugin**: Copilot CLI workflow skills for handling PR reviews, rebasing,
  investigating problems, drafting standups and coordinating work between
  environments. Every skill asks for explicit approval before acting and
  defaults to a dry run.
- **Context library**: a short bootstrap file that is always loaded and holds a
  route table, plus Markdown topic pages that agents open only when a task
  calls for them (progressive disclosure). Its installer shows a preview first,
  keeps immutable snapshots, and can roll back.
- **Integration recipes**: MCP configuration examples that contain no
  credentials, together with a template for writing up new integrations.

Take whichever parts are useful to you and ignore the rest. Digits does not
image workstations, provision repositories, or enforce any organization's
policy.

If you want to apply the same ideas to your own tools and team, read
[Build your own Digits](docs/build-your-own.md).

## Status

Digits is open source under the [MIT License](LICENSE). It is an early
release: it is tested on macOS, and the dashboard and lifecycle extensions rely
on experimental Copilot CLI extension APIs that may change between CLI
versions. Issues and pull requests are welcome.

## Requirements

- macOS, the only platform Digits is tested on.
- [tmux](https://github.com/tmux/tmux) 3.2 or later.
- Python 3.9 or newer.
- Node.js.
- [GitHub Copilot CLI](https://docs.github.com/en/copilot/how-tos/copilot-cli), or
  [Claude Code](https://code.claude.com/docs) for the dashboard (see
  [Claude Code](#claude-code)). The plugin and context library also load in
  Claude Code; the two plugin extensions are Copilot-only.
- Optional: fish. The launcher opens a fish login shell in every environment
  when fish is installed, and your login shell (`$SHELL`) otherwise.
- Optional: [Ghostty](https://ghostty.org/) for the keyboard shortcuts, and
  Visual Studio Code for the `md-view` Markdown viewer.

You sign in to Copilot on your own; Digits never handles that. GitHub or MCP
authentication only matters for the workflows that talk to those services.

The dashboard extension relies on experimental Copilot SDK APIs, so turn on
experimental mode with `/settings experimental on`. It has been tested with
Copilot CLI versions 1.0.100 to 1.0.105; check that it behaves before relying
on it with any other version.

## Quick start

Run every command from the repository root. Each installer only shows what it
would do until you pass `--apply`.

### Dashboard

```bash
python3 install.py            # dry run: print the plan, change nothing
python3 install.py --apply    # perform the installation
~/.local/bin/ai-agents        # start the session, or reattach to it
```

The installer copies five runtime files: the `ai-agents` launcher, the
`md-view` viewer, the dashboard's tmux configuration, and the extension's
`extension.mjs` and `state.mjs`. It also creates any of the ten environment
directories that do not exist yet.

It does not clone repositories, start chats, sign you in to anything, or edit
your Copilot settings, Ghostty configuration, MCP configuration or global tmux
configuration.

For Claude Code instead of Copilot, add `--host claude` to both commands and
follow [Claude Code](#claude-code).

### Plugin

```bash
copilot plugin marketplace add /path/to/digits
copilot plugin install digits@digits
```

[plugin/README.md](plugin/README.md) explains how to update the plugin and how
to set up each skill. Some skills only become useful once you have written
local, non-secret bindings for them.

For Claude Code, load the same folder as a plugin. The skills appear as
`/digits:<name>`, except `/digits:done`, which needs the Copilot extensions:

```bash
claude --plugin-dir /path/to/digits/plugin
```

### Context library

```bash
python3 context_install.py               # dry run: print the plan, change nothing
python3 context_install.py --apply       # install or update the context
python3 context_install.py --rollback    # dry run of returning to the previous snapshot
```

If you already have a Copilot instruction file, the installer only takes it
over when you adopt it explicitly with the hash shown in the preview
(`--adopt-sha256`). Receipts, backups and private bindings stay on your
machine. See [context/README.md](context/README.md) for details.

For Claude Code, add `--host claude`. The installer writes
`~/.claude/digits/CLAUDE.md` and its own receipt, and never edits your
`CLAUDE.md` files. Claude Code does not load that file on its own. To use it
only in the dashboard's chats, link it into each environment folder:

```bash
for d in left_pinky left_ring left_middle left_pointer left_thumb \
         right_thumb right_pointer right_middle right_ring right_pinky; do
  ln -s ~/.claude/digits/CLAUDE.md ~/$d/CLAUDE.md
done
```

A link rather than an `@~/.claude/digits/CLAUDE.md` import line, because Claude
Code asks once per folder before loading an import from outside it. To use it in
every chat, add that import line to `~/.claude/CLAUDE.md` instead. The context
links its topic pages under `~/.claude/digits/`; if Claude Code asks before
reading them, allow `Read(~/.claude/digits/**)` in your Claude Code permissions.

### Integrations

[mcp/README.md](mcp/README.md) describes how to set up MCP servers while
keeping every secret out of Git, and how to check each service with a harmless
read before trusting it.

## Dashboard

The launcher creates the managed tmux session `ai-agents`, or reattaches to it
when it is already running.

| Window | Environment | Window | Environment |
|---|---|---|---|
| 1 | `left_pinky` | 6 | `right_thumb` |
| 2 | `left_ring` | 7 | `right_pointer` |
| 3 | `left_middle` | 8 | `right_middle` |
| 4 | `left_pointer` | 9 | `right_ring` |
| 5 | `left_thumb` | 10 | `right_pinky` |

Each environment is a separate directory in your home folder by default. To
keep them somewhere else, set `AI_AGENTS_ROOT` to an absolute path (for
example `export AI_AGENTS_ROOT=~/Code/agents` in your shell profile) or pass
`--root DIR` (with `ai-agents` or `ai-agents --no-attach` only); `--root` wins
over the variable. Only `~` and `~/…` are expanded, and a root with a
backslash or a control character is refused. The launcher only checks the ten
directories exist there, so create them yourself: the installer still creates
them in your home. Every shell the launcher creates starts with
`AI_AGENTS_ROOT` set to the root, and the root is also exported to the tmux
session for panes you open later, so `digits-claude` (and `ai-agents
--restart`) finds the same environments. A running session keeps its root:
a plain `ai-agents` reuses it, and a different root is refused until you
kill the session with `tmux kill-session -t ai-agents` (this ends every chat
in the session). Put a distinct
clone in each one (never worktrees that share a repository) and start Copilot
by hand wherever you want a chat.

Running the launcher again keeps every existing pane and the window you are
on. If a window has an unexpected name it refuses to continue rather than
replace it, and it never restarts a chat. Closing the terminal only detaches;
the session keeps running. After a reboot the environments come back as fresh
shells, but conversations are not restored.

### States

| State | Meaning |
|---|---|
| READY | A plain shell, or a chat that has not started any work yet |
| WORKING | The chat is busy with a turn, or another program runs in the foreground |
| SUBAGENTS | Child agents are running for the chat |
| WATCHING | The chat is waiting only on a background shell it is attached to |
| NEEDS YOU | The chat is waiting for your input or a permission decision |
| QUESTION | Claude Code only, in colour213: the chat asked through AskUserQuestion and is shown so while that question is open |
| ERROR | The session reported an error, or the pane has died |
| COPILOT / UNKNOWN | COPILOT: Copilot is running but nothing has been published yet; UNKNOWN: state tracking failed |
| YOUR TURN | The chat finished its turn and the next move is yours |
| WAITING | An idle chat with a waiting reason you typed in |

Pending input and errors always outrank any background wait. Services started
in detached mode are not counted as watched shells.

WORKING, SUBAGENTS and WATCHING show how long the current run has been going.
YOUR TURN shows how long the turn took and the clock time it finished, for
example `4m12s @09:46`. WAITING shows the time since the turn finished.

To record why you are waiting, right-click a YOUR TURN entry and type a
reason. Submitting an empty reason clears it, and so does the chat starting
work again. It is a personal note, not a scheduling feature.

The view redraws every second using tmux's own format strings. Chat states
come from Copilot lifecycle events and SDK snapshots rather than polling. If
tracking breaks, the entry shows UNKNOWN and the extension retries with a
capped backoff.

### Claude Code

The dashboard also works with Claude Code chats. Claude Code has no extension
SDK, so a hook script publishes the same states:

```bash
python3 install.py --host claude            # preview
python3 install.py --host claude --apply    # installs the hook and ~/.local/bin/digits-claude
```

The installer never edits Claude Code settings. Merge the `hooks` from
[claude/settings.json](claude/settings.json) into `~/.claude/settings.json`
yourself. Chats that were already running keep the hooks they started with.

Start chats with `digits-claude` rather than `claude`. It names each session
after its environment (`left-pinky` … `right-pinky`), so chats can list and
message each other with Claude Code's own session tools, and passes any other
arguments on (`digits-claude --continue`). To load the skills straight from a
checkout, so edits take effect after `/reload-skills`, set
`DIGITS_PLUGIN_DIR=/path/to/digits/plugin` in your shell profile.

Chats keep the shell environment they started with. After changing your
profile, run `ai-agents --restart` (or `/digits:restart-chats` in a chat) to
restart the idle chats one at a time: each gets `/exit`, a fresh login shell
and `digits-claude --continue`. Busy chats, chats with a draft in the
composer, Copilot chats and the chat running the command are left alone and
listed with the reason. Name environments to limit it, for example
`ai-agents --restart left-ring right-pinky`.

Claude Code chats show READY, WORKING, SUBAGENTS, NEEDS YOU, QUESTION, YOUR
TURN and ERROR. QUESTION is shown while an AskUserQuestion prompt is open and
clears when you answer it. WATCHING is not produced, and the Markdown shortcut has no session
folder to open. Claude Code sends no event when you approve a permission or
press Esc, so NEEDS YOU lasts until the next tool event (for a long-running
approved command, until it ends), and an
interrupted chat shows WORKING until Claude Code reports it idle (about a
minute) or you type again. The hook only touches panes in the `ai-agents`
session; your other Claude Code chats are left alone. Claude Code's own
after-turn background agents are ignored, so a finished chat stays on YOUR TURN.

### Shortcuts

Click an entry to switch to that environment. The **hotkeys** button in the
top-right corner opens a menu listing every shortcut and runs the one you
pick.

Two optional fragments add keyboard shortcuts:
[terminal/ghostty-keybindings.conf](terminal/ghostty-keybindings.conf) for
Ghostty and
[terminal/ai-agents-shortcuts.tmux.conf](terminal/ai-agents-shortcuts.tmux.conf)
for tmux.

| Shortcut | Action |
|---|---|
| Cmd+1 … Cmd+9, Cmd+0 | Go to window 1 … 10 |
| Cmd+Shift+] / Cmd+Shift+[ | Next / previous window, wrapping around |
| Cmd+; | Back to the previous window |
| Cmd+` | Next chat that wants attention: NEEDS YOU, then QUESTION, then YOUR TURN, never WAITING |
| Cmd+Shift+M | Open that chat's most recent session Markdown in `md-view` |

`md-view` renders Markdown in a separate VS Code instance with its own profile
at `~/Library/Application Support/digits-markdown-viewer`, so your normal
editor windows are left alone.

The installer touches neither Ghostty nor your global tmux file, so adopting
the shortcuts is manual:

1. Merge the Ghostty bindings into your Ghostty configuration.
2. Copy the tmux fragment to `~/.tmux/ai-agents-shortcuts.conf`.
3. Add `source-file ~/.tmux/ai-agents-shortcuts.conf` to `~/.tmux.conf`.

Be aware that the Ghostty bindings replace Ghostty's tab shortcuts, its Cmd+0
font-size reset, and the macOS Cmd+` window cycling. The tmux fragment uses
`user-keys[180]` through `user-keys[194]` for the whole tmux server, so make
sure nothing else claims them; only the managed session reacts to them.

### Updating and removal

The installer only manages files it created. A file that was already there is
refused, even if it is byte-for-byte identical. The receipt at
`~/.local/state/digits/dashboard.json` records each installed file's hash and
mode and the directories the installer created. Running `--apply` again
replaces only owned files that are still unmodified; a file you edited blocks
both updates and removal until you deal with it.

```bash
python3 install.py --uninstall            # preview the removal
python3 install.py --uninstall --apply    # remove owned, unmodified files
```

Removal keeps directories that existed beforehand or still contain something,
and does not stop running tmux sessions. Chats that are already open must be
reloaded while idle to pick up or drop the extension.

To install by hand instead, copy `bin/ai-agents` to `~/.local/bin/`,
`terminal/ai-agents.conf` to `~/.tmux/`, and `copilot/extensions/env-dashboard/`
to `~/.copilot/extensions/`.

[copilot/settings.json](copilot/settings.json) is a reviewed example of
Copilot settings; the installer never applies it.

## Make it yours

- **Private bindings**: keep non-secret Markdown facts such as account names,
  profiles, channels and repository lists in `~/.config/digits/context/` on
  your machine. The bootstrap tells agents where to find them, and nothing ever
  exports them. Templates live in
  [examples/private-bindings/](examples/private-bindings/).
- **Domain pages and routes**: add new topic pages under `context/`, and give
  each one a row in the route table of
  [context/bootstrap.md](context/bootstrap.md) that tells agents when to open
  it.
- **Routing fixtures**: before you change a page, record the correction that
  keeps coming back as a small case in
  [tests/fixtures/context-routing.json](tests/fixtures/context-routing.json).
- **Private-terms guard**: list names that must never be published (people,
  companies, internal hosts) in `~/.config/digits/private-terms.txt`, one per
  line, or point `DIGITS_PRIVATE_TERMS` at another file. Findings from
  `scripts/check_repository.py` look like `path:line: private term #N`, where
  `N` is the line number in the terms file; the term itself is never printed.
  Matching ignores case, and blank lines and `#` comment lines are skipped.
  Without the default file the guard is skipped, but a `DIGITS_PRIVATE_TERMS`
  value that names a missing file is an error.

## Safety model

- **Preview first**: neither installer writes anything without `--apply`. Both
  keep ownership receipts, refuse files they did not create, and preserve your
  edits.
- **Staged approval**: skills treat planning, preview, publication, release and
  outward communication as separate steps. Passing CI, a merge, or another
  agent's suggestion never unlocks the next step.
- **No credentials in Git**: examples contain placeholders only. Secrets belong
  in the operating-system keychain or in environment variables; OAuth caches
  and live MCP files stay on your machine.
- **Guards**: the repository guard blocks private artifacts, machine-specific
  home paths, invalid JSON and, when configured, private terms. The secret
  guard runs detect-secrets without network access and reports where a finding
  is, never what it is.
- **Executable code**: extensions and hooks run as code with your permissions;
  review them before installing.

## Project layout

```text
bin/                 launcher (ai-agents) and Markdown viewer (md-view)
terminal/            dashboard tmux configuration and optional tmux/Ghostty fragments
copilot/             dashboard extension and a reviewed settings example
claude/              Claude Code dashboard hook and its settings fragment
plugin/              the digits Copilot CLI plugin: skills and lifecycle extensions
context/             bootstrap, topic pages and version of the context library
examples/            private-binding templates
mcp/                 MCP integration recipes and a placeholder configuration
scripts/             repository and secret guards, publication preflight
tests/               Python tests for installers, guards, context and helpers
docs/                build-your-own guide, provenance and release checklist
spec/                functional specification used for the clean-room build
install.py           dashboard installer
context_install.py   context library installer
```

The plugin ships fifteen skills: `assess-and-address`, `challenge-pass`,
`done`, `draft-pr-sweep`, `inter-env`, `investigate`, `rebase-pr`,
`request-review`, `restart-chats`, `review-reactions`, `self-improve`,
`standup-update`, `summarize`, `token-usage` and `update-shared-workflows`.

## Verification

Run these from the repository root with tmux and jq installed:

```bash
python -m unittest discover -s tests
python -m unittest discover -s plugin/skills/inter-env -p 'test_*.py'
for helper in plugin/skills/standup-update/*.sh; do bash -n "$helper"; done
node --check copilot/extensions/env-dashboard/extension.mjs
node --test copilot/extensions/env-dashboard/*.test.mjs
for module in plugin/com.github.copilot/extensions/*/*.mjs; do node --check "$module"; done
node --test plugin/com.github.copilot/extensions/*/*.test.mjs
```

The tests use throwaway home directories, private tmux sockets and mocked
services. They send no chat messages and call no live service, so passing
tests tell you nothing about MCP authentication. On a real installation, also
check the window order, click targets, state changes and input prompts
yourself.

The guards need the pinned scanner, installed in an isolated environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
git add -A    # the index must hold exactly the commit you plan to make
python scripts/check_repository.py
python scripts/check_secrets.py
```

Neither guard runs unless the index matches the working tree. Untracked files
that are not ignored are checked too. Review every finding properly; blanket
exemptions are not the answer.

Before you push to a public remote or post a pull request, check what you are
about to publish:

```bash
python scripts/check_publication.py --range origin/main..HEAD
python scripts/check_publication.py --text pr-body.md    # or --text - for stdin
```

The publication preflight requires GitHub noreply author and committer emails
and noreply `Co-authored-by`-style trailers, and scans names, full commit
messages, changed paths, added lines and PR text for private terms, home
paths, email addresses outside the example domains and, with the pinned
detect-secrets, secrets. Binary changes and a range that selects no commits
are failures. Like the guards, it reports where, never what. Without a
private-terms file it says so and runs the other checks.

## Contributing and security

Read the [contributing guide](.github/CONTRIBUTING.md), the
[security policy](.github/SECURITY.md) and the
[code of conduct](.github/CODE_OF_CONDUCT.md) before contributing.
[Provenance](docs/provenance.md) explains where Digits came from, how it was
rebuilt from scratch, and what was deliberately left out.

## Acknowledgements

Several workflow skills were inspired by
[Ken Crowell](https://github.com/oeuftete)'s personal agent harness. See
[Provenance](docs/provenance.md#acknowledgements).
