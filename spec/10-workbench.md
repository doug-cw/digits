# 10 Workbench: launcher, dashboard, Markdown viewer, shortcuts, installer

This file specifies the Workbench component listed in `00-overview.md`. It
covers every file the component ships, the runtime contracts between them
(tmux options, Copilot SDK calls, process arguments), the installer, and the
acceptance tests. Literal values shown in `code` are interface contracts and
MUST be reproduced exactly unless the text says the wording is free.

## 1. Deliverables

| Repository path | Git mode | Installed to (relative to `HOME`) | Installed mode | Purpose |
|---|---|---|---|---|
| `bin/ai-agents` | 100755 | `.local/bin/ai-agents` | `0755` | Launcher, attention jump, Markdown shortcut (Python 3) |
| `bin/md-view` | 100755 | `.local/bin/md-view` | `0755` | Markdown viewer wrapper around VS Code (Python 3) |
| `terminal/ai-agents.conf` | 100644 | `.tmux/ai-agents.conf` | `0644` | Session-scoped dashboard configuration sourced by the launcher |
| `copilot/extensions/env-dashboard/extension.mjs` | 100644 | `.copilot/extensions/env-dashboard/extension.mjs` | `0644` | Copilot CLI extension (runtime/transport) |
| `copilot/extensions/env-dashboard/state.mjs` | 100644 | `.copilot/extensions/env-dashboard/state.mjs` | `0644` | Pure activity state machine |
| `copilot/extensions/env-dashboard/extension.test.mjs` | 100644 | not installed | | Extension runtime tests (`node:test`) |
| `copilot/extensions/env-dashboard/state.test.mjs` | 100644 | not installed | | State machine tests (`node:test`) |
| `terminal/ai-agents.tmux.conf` | 100644 | not installed | | Optional include for the user's own tmux configuration |
| `terminal/ai-agents-shortcuts.tmux.conf` | 100644 | not installed | | Optional tmux key bindings paired with Ghostty |
| `terminal/ghostty-keybindings.conf` | 100644 | not installed | | Optional Ghostty key bindings |
| `terminal/ghostty.conf` | 100644 | not installed | | Optional Ghostty bell settings |
| `copilot/settings.json` | 100644 | not installed | | Reviewed Copilot settings example |
| `install.py` | 100644 | not installed | | Preview-first installer/remover |
| `tests/test_installer.py`, `tests/test_launcher.py` | 100644 | not installed | | Python `unittest` suites |

Both executables start with a `#!/usr/bin/env python3` shebang and use only the
Python standard library. Neither has a `.py` suffix; tests load them by path.

## 2. Shared constants

- Session name: `ai-agents`. Exact-match tmux target prefix used for every
  command aimed at the session: `=ai-agents:` (window `N` is `=ai-agents:N`).
- Session marker: session user option `@ai-agents-managed` with value `1`.
  Only a session carrying this marker is treated as managed.
- Window table (index, environment directory under `HOME`, window name). The
  window name is the directory name with `_` replaced by a space and each word
  capitalised:

  | Index | Directory | Window name |
  |---|---|---|
  | 1 | `left_pinky` | `Left Pinky` |
  | 2 | `left_ring` | `Left Ring` |
  | 3 | `left_middle` | `Left Middle` |
  | 4 | `left_pointer` | `Left Pointer` |
  | 5 | `left_thumb` | `Left Thumb` |
  | 6 | `right_thumb` | `Right Thumb` |
  | 7 | `right_pointer` | `Right Pointer` |
  | 8 | `right_middle` | `Right Middle` |
  | 9 | `right_ring` | `Right Ring` |
  | 10 | `right_pinky` | `Right Pinky` |

- Paths (all derived from the current user's home; never hardcoded):
  - Dashboard configuration read by the launcher: `~/.tmux/ai-agents.conf`.
  - Launcher lock: `~/Library/Caches/env-sync/ai-agents.lock`.
  - Markdown viewer profile: `~/Library/Application Support/digits-markdown-viewer`.
  - Installer receipt: `~/.local/state/digits/dashboard.json`.
  - Launcher as invoked by tmux bindings: `$HOME/.local/bin/ai-agents` (shell
    expansion of `HOME` in the tmux server's environment at run time).

### 2.1 Pane options written by the extension (the dashboard data contract)

All are tmux **pane** user options on the pane in which Copilot runs.

| Option | Value | Written by |
|---|---|---|
| `@env-dashboard-owner` | Decimal PID of the Copilot process hosting the extension | extension |
| `@env-copilot-state` | One of `READY`, `WORKING`, `SUBAGENTS`, `WATCHING`, `NEEDS YOU`, `ERROR`, `YOUR TURN`, `UNKNOWN` | extension |
| `@env-copilot-since` | Decimal Unix seconds, or empty string | extension |
| `@env-copilot-took` | Decimal non-negative seconds, or empty string | extension |
| `@env-session-dir` | Absolute local session-state folder of the chat; unset when none/remote | extension |
| `@env-waiting-reason` | Free text typed by the user; empty or unset means none | right-click prompt |
| `@env-waiting-owner` | Copy of `@env-dashboard-owner` at the moment a reason was saved | right-click prompt |

`@env-copilot-reason` (published by a retired predecessor) MUST be ignored
everywhere. Older chats may still publish legacy hand-back labels in
`@env-copilot-state`: `ACTION`, `ANSWERED`, `BLOCKED`, `COMPLETE`, `DECIDE`,
`PARKED`, `REVIEW`, `WAITING`. Together with `YOUR TURN` these nine strings form
the **idle label set**; the dashboard treats every member as `YOUR TURN`.

## 3. Launcher `bin/ai-agents`

### 3.1 Command line

| Invocation | Effect |
|---|---|
| `ai-agents` | Ensure the session (3.2) under the lock, then attach (3.3) |
| `ai-agents --no-attach` | Ensure the session under the lock, print `Ready: ai-agents` to stdout, exit 0 |
| `ai-agents --next-attention` | Jump to the next chat needing attention (3.4). No lock, no session creation |
| `ai-agents --markdown PANE [--client CLIENT]` | Open the newest session Markdown of tmux pane `PANE` (3.5). No lock, no session creation |

- `--no-attach`, `--next-attention` and `--markdown` are mutually exclusive;
  combining them is an argument-parser usage error (exit 2, usage on stderr).
- `--client NAME` is accepted with any mode but hidden from `--help`; it is only
  meaningful with `--markdown`, where status messages are shown on that client.
- `--help` prints a one-line description of the tool (wording free).

The tmux executable is the first `tmux` on `PATH`, falling back to the bare
name `tmux`. The fish executable is the first `fish` on `PATH`, or absent.
The login shell is the value of `SHELL`, or absent. The **environment shell**
is fish when present; otherwise the login shell, when it is an absolute path
to an executable regular file; otherwise absent.

Every tmux call is run with captured text output; its stdout is returned with
surrounding whitespace stripped. A non-zero exit of any tmux call other than
session listing (3.2 step 2) aborts the command (see 3.6).

### 3.2 Ensuring the session (create or reconnect)

Before ensuring, the launcher creates `~/Library/Caches/env-sync` (with
parents, if missing), opens `ai-agents.lock` inside it for writing (creating or
truncating it) and takes a **blocking exclusive** `flock` on it. The lock is
held for the whole ensure step and released before attaching, so concurrent
launches are serialised and never race to create windows.

Ensure performs, in order:

1. If `~/.tmux/ai-agents.conf` is not an existing regular file: fail with a
   message containing `Missing session configuration:` and the path.
2. List sessions (`list-sessions -F '#{session_name}'`). If that fails and its
   stderr contains `no server running` or `No such file`, treat the list as
   empty; any other failure aborts with the tmux stderr text. The session is
   **new** if `ai-agents` is not in the list.
3. If the session exists:
   - Read the session option `@ai-agents-managed` (quiet, value only). If it is
     not exactly `1`, fail with a message that contains the word `unmanaged`
     and states that the session will not be modified. Nothing is changed.
   - Read its windows as (index, name) pairs.
4. Every existing window must have an index from 1 to 10 **and** exactly the
   expected name for that index. Otherwise fail with a message beginning
   `Unexpected window ` followed by the target (`=ai-agents:<index>`), the
   actual name, and a refusal to replace it. An extra window (index 0, 11, …)
   or a renamed window therefore blocks the launcher. Nothing is changed.
5. The **missing** windows are the indices 1–10 not present (all ten for a new
   session). For each missing window, `HOME/<directory>` must be an existing
   directory that is not a symlink; otherwise fail with a message containing
   `Missing independent environment:` and the path. All these checks finish
   before anything is created.
6. If at least one window is missing and the environment shell is absent,
   fail with a message stating that a login shell is required to create
   environment shells (install fish or set `SHELL`).
7. Each new shell runs the command `/usr/bin/env -u VIRTUAL_ENV <shell> -l`,
   where `<shell>` is the environment shell (a login shell with `VIRTUAL_ENV`
   removed, so a virtualenv active in the launching shell does not leak in). Its start directory (`-c`) is the
   environment directory.
8. New session only: create it detached with the first missing window
   (window 1's name and directory), printing that window's id; then set the
   session option `@ai-agents-managed` to `1` immediately.
9. Always set these **session-scoped** options on `=ai-agents:` (global options
   are never touched): `base-index 1`, `destroy-unattached off`,
   `renumber-windows off`, `mouse on`.
10. New session only: if the first window's index is not 1 (because the server's
    global `base-index` differs), move it to index 1.
11. Create each remaining missing window, detached, at its exact index
    (`=ai-agents:<index>`), with its name, start directory and shell command.
    Existing windows and panes are never killed, respawned or re-created.
12. For each index 1–10 set window options `automatic-rename off` and
    `allow-rename off` so names stay stable.
13. Source `~/.tmux/ai-agents.conf` (section 6). This happens on every ensure,
    re-applying the dashboard without disturbing pane options such as waiting
    reasons.
14. New session only: select window 1. For an existing session the currently
    selected window is left as is.

Consequences that MUST hold: reconnecting leaves window ids, pane ids and pane
PIDs unchanged; a single killed window is recreated without touching the
others; a killed session is recreated with ten fresh shells (new ids); chats
are never restarted; after a reboot shells are new and conversations are not
restored.

### 3.3 Attaching

After a successful ensure:

- `--no-attach`: print exactly `Ready: ai-agents` and exit 0.
- Else, if the environment variable `TMUX` is set (non-empty): run
  `switch-client -t =ai-agents:` and exit 0.
- Else: replace the launcher process (exec, no child) with
  `tmux attach-session -t =ai-agents:`. Closing the terminal later detaches
  without stopping the session (`destroy-unattached off`).

### 3.4 Next chat needing attention (`--next-attention`)

1. Read `@ai-agents-managed` of `=ai-agents:`; if not `1`, fail with a message
   containing `unmanaged` (if the session does not exist the tmux error aborts).
2. List windows with format `#{window_index}|#{window_active}|#{E:@hand-status-state}`
   (the state of each window's active pane, section 6.2). The current window is
   the one whose active flag is `1`.
3. Tiers are checked in order: first `NEEDS YOU`, then `YOUR TURN`. `WAITING`,
   `WORKING`, `READY` and every other state are never candidates. For a tier,
   candidates are windows whose state equals the tier label, whose index is
   between 1 and 10 inclusive, and which are not the current window.
4. In the first tier with candidates, select the smallest candidate index that
   is greater than the current index; if none is greater, wrap to the smallest
   candidate. Then exit 0.
5. If no tier has candidates, show the tmux message
   `No other chats need attention` on the session (`display-message -t
   =ai-agents:`) and exit 0 without changing the selection.

Because the state comes from the tmux format, a pane that is a plain shell
shows `READY` even if a stale `@env-copilot-state` remains on it, so it is
never a candidate.

### 3.5 Markdown shortcut (`--markdown PANE [--client CLIENT]`)

1. Check `@ai-agents-managed` as in 3.4 step 1.
2. Query `PANE` for `#{session_name}` and `#{@env-session-dir}` (one
   `display-message -p` with a tab separator). If the session name is not
   `ai-agents`, fail with a message containing `not in the ai-agents session`.
3. Status messages below are shown with `display-message`, aimed at
   `-c CLIENT` when `--client` was given, otherwise at tmux's default client.
4. If the folder value is empty, not an absolute path, or not an existing
   directory: show `No Copilot session folder for this chat`, exit 0.
5. Candidate documents: `<folder>/plan.md`, plus every `*.md` file found
   recursively under `<folder>/files`, `<folder>/research` and
   `<folder>/checkpoints`. Other subtrees (notably `rewind-file-snapshots`,
   which holds copies of repository files) are ignored. Keep only candidates
   that are regular files and not symlinks; recursion SHOULD not descend into
   symlinked directories. Pick the one with the greatest modification time;
   on a tie the earlier candidate in the order above wins (plan.md first, then
   files, research, checkpoints).
6. If there is no candidate: show `No Markdown in this chat's session folder yet`,
   exit 0.
7. Run `md-view <document>` where `md-view` is the file named `md-view` in the
   same directory as the launcher's own resolved (symlink-free) path, capturing
   its output. If it exits non-zero, show the last line of its stderr as a
   message, or `md-view failed` when stderr is empty. The launcher exits 0 in
   all these message cases.

### 3.6 Errors and exit codes

| Situation | Exit | stderr |
|---|---|---|
| Success, including "no attention"/"no folder"/"no Markdown"/viewer failure messages | 0 | nothing |
| Argument error | 2 | argparse usage |
| Validation failure, OS error, failing tmux command | 1 | one line `ai-agents: <detail>`; for a failing tmux command `<detail>` is that command's stripped stderr |

### 3.7 Testability contract

The launcher MUST be importable as a module from its path (without executing
`main`) and expose replaceable module-level hooks that every function reads at
call time: the home directory, the configuration path, the fish executable
path, the login shell path, the function that runs one tmux command and
returns stripped stdout, and the function that lists session names. It MUST also expose the window table,
the session name, the target prefix, and callable entry points for ensure,
next-attention and Markdown (the reference uses `HOME`, `CONFIG`, `FISH`,
`LOGIN_SHELL`, `tmux`, `list_sessions`, `WINDOWS`, `SESSION`, `TARGET`, `TMUX`,
`ensure_session`, `focus_next_attention`, `show_markdown(pane, client=None)`;
equivalent names are acceptable if tests are adapted).

## 4. Markdown viewer `bin/md-view`

### 4.1 Command line and behaviour

`md-view FILE [FILE ...]` (at least one file; none is a usage error, exit 2).

1. Each argument has `~` expanded and is made absolute with symlinks resolved.
   If any resolved path is not an existing regular file, fail with
   `Not a file: <p1>, <p2>` listing every offending resolved path joined by
   `, `. This check happens before searching for VS Code or touching the
   profile, so no editor process is started.
2. Locate the VS Code CLI: `code` on `PATH`; else the first executable
   `<bundle>/Contents/Resources/app/bin/code`, trying `<bundle>` =
   `/Applications/Visual Studio Code.app` and then the same bundle name under
   `~/Applications`
   (tmux `run-shell` and launchd may lack the login `PATH`). If none, fail with
   a message saying VS Code's `code` command was not found.
3. Ensure the dedicated profile `P = ~/Library/Application Support/digits-markdown-viewer`:
   create `P/extensions` and `P/User` (with parents) if missing. If
   `P/User/settings.json` does **not** exist, create it with the settings in
   4.2 serialised as JSON with 2-space indentation, non-ASCII characters kept
   literally, and a trailing newline. An existing settings file is never read,
   merged or rewritten, so user edits persist.
4. Build the child environment from the current one minus every variable whose
   name starts with `VSCODE_` and minus `ELECTRON_RUN_AS_NODE` (otherwise a
   call from a VS Code terminal would open files in that window).
5. Run `code --user-data-dir P --extensions-dir P/extensions --reuse-window
   <resolved files...>` with stdin and stdout attached to the null device and
   stderr captured; wait for it. Because the user data directory is private,
   the first call starts a separate VS Code instance with its own window and
   later calls add tabs to that window; the user's normal editor windows are
   never used.
6. Errors (validation, missing CLI, OS errors, non-zero `code` exit) print one
   line `md-view: <detail>` to stderr and exit 1; for a failed `code` run the
   detail is its stripped stderr (or the error text when empty). Success exits
   0 silently.

### 4.2 Viewer settings written once

| Key | Value |
|---|---|
| `chat.disableAIFeatures` | `true` |
| `extensions.ignoreRecommendations` | `true` |
| `update.mode` | `"none"` |
| `security.workspace.trust.untrustedFiles` | `"open"` |
| `window.restoreWindows` | `"none"` |
| `window.title` | `"Markdown — ${activeEditorShort}"` (em dash, U+2014) |
| `workbench.activityBar.location` | `"hidden"` |
| `workbench.editorAssociations` | object `{"*.md": "vscode.markdown.preview.editor"}` (Markdown opens as rendered preview) |
| `workbench.enableExperiments` | `false` |
| `workbench.layoutControl.enabled` | `false` |
| `workbench.startupEditor` | `"none"` |
| `workbench.statusBar.visible` | `false` |
| `workbench.tips.enabled` | `false` |

Key order in the written file is not significant (the reference writes
`workbench.editorAssociations` first).

## 5. Copilot CLI extension `env-dashboard`

### 5.1 Packaging and SDK surface

- Two ES modules in one folder. `extension.mjs` is the entry point Copilot
  CLI loads from `~/.copilot/extensions/env-dashboard/`; it imports the state
  class from the sibling `./state.mjs` (relative specifier) and the SDK from
  the bare specifier `@github/copilot-sdk/extension`, named export
  `joinSession`. It uses `execFileSync` from `node:child_process`, and the
  global `setTimeout`/`clearTimeout`. No other dependencies.
- Copilot CLI experimental mode must be enabled for the SDK APIs used. Validated
  against Copilot CLI versions 1.0.100 through 1.0.105.
- `joinSession({ onEvent })` is called exactly once with an options object that
  registers **no tools** (no `tools` property, or an empty one). It resolves to
  a session object; the extension uses only:

  | Call | Resolves to (fields used) |
  |---|---|
  | `session.getEvents()` | array of persisted events |
  | `session.rpc.metadata.activity()` | `{ hasActiveWork: boolean }` |
  | `session.rpc.metadata.isProcessing()` | `{ processing: boolean }` |
  | `session.rpc.metadata.snapshot()` | `{ isRemote: boolean, workspacePath: string? }` |
  | `session.rpc.permissions.pendingRequests()` | `{ items: [{ requestId }] }` |
  | `session.rpc.tasks.list()` | `{ tasks: [{ type, status, toolCallId?, executionMode?, attachmentMode? }] }` |

- An event is `{ type: string, timestamp?: ISO-8601 string, data?: object,
  agentId?: string }`. A truthy `agentId` marks an event from a child agent.

### 5.2 Enablement and tmux transport

- `TMUX_PANE` must match `^%\d+$`. The tmux socket path is the value of `TMUX`
  with its last two comma-separated fields removed (the remaining fields are
  re-joined with commas, so a socket path containing commas survives). The
  extension is **enabled** only when both a non-empty socket path and a valid
  pane id exist. When disabled it still joins the session but ignores all
  events and never calls tmux.
- Every tmux call is a synchronous `execFileSync("tmux", ["-S", <socket>, ...])`
  with UTF-8 output, a 2000 ms timeout, stdin ignored, stdout and stderr piped,
  and the output trimmed. Multiple tmux commands in one call are separated by
  a standalone `;` argument.

### 5.3 Publishing

- **State publish.** Compute `label`, `since`, `took`: when tracking has failed,
  `UNKNOWN`, `""`, `""`; otherwise the state's label and its `since`/`took`
  rendered as decimal strings (`""` when undefined). The dedup key is the three
  values joined. Do nothing if disabled or the key equals the last
  successfully published key. Otherwise issue **one** tmux call that, in this
  order, sets pane options on `TMUX_PANE`: `@env-dashboard-owner` = PID,
  `@env-copilot-state` = label, `@env-copilot-since` = since,
  `@env-copilot-took` = took, then `refresh-client -S`. Each `set-option` uses
  `-p -t <pane> <option> <value>` so the value is the argument immediately after
  the option name. Remember the key only after the call succeeds; a thrown
  error propagates to the caller.
- **Folder publish.** Skipped when disabled. Call `metadata.snapshot()`; the
  folder is `workspacePath` when `isRemote` is false and the path is non-empty,
  otherwise empty. If it equals the last published folder (initially none, so
  the first call always writes), do nothing. Otherwise either set
  `@env-session-dir` to the folder (folder is the final argument) or unset it
  (`set-option -p -u -t <pane> @env-session-dir`). Any failure is logged to
  stderr with a message containing `could not publish the session folder` and
  is **not** a tracking failure: no `UNKNOWN`, no retry.

### 5.4 State machine (`state.mjs`)

Exports a class (reference name `DashboardState`) with a no-argument
constructor, read-only properties `label`, `since`, `took`, and methods
`accept(event)`, `setActivity(active, timestamp?)`, `setProcessing(processing)`,
`setTasks(tasks, timestamp?)`. It has no I/O.

#### 5.4.1 Internal fields (initial value)

| Field | Initial | Meaning |
|---|---|---|
| working | false | Parent turn is in progress |
| failed | false | Last session failure not yet cleared |
| started | false | Any work has ever started |
| pending | empty set | Outstanding input requests, keyed `<kind>:<requestId>` |
| processing | false | Parent model/tool processing is under way |
| shells | false | A running, attached shell task exists |
| agents | empty map | Running child agents: toolCallId → executionMode |
| tools | empty map | In-flight parent tool calls: toolCallId → "is an explicit agent wait" |
| startedAt | undefined | Unix seconds the current/last run started |
| doneAt | undefined | Unix seconds the last run settled |

#### 5.4.2 Label (first matching row wins)

| # | Condition | Label |
|---|---|---|
| 1 | pending is non-empty | `NEEDS YOU` |
| 2 | failed | `ERROR` |
| 3 | working, agents non-empty, and (not processing, or tools non-empty and every tool is an agent wait or its id maps to an agent whose mode is `sync`) | `SUBAGENTS` |
| 4 | working, shells, not processing | `WATCHING` |
| 5 | working | `WORKING` |
| 6 | agents non-empty (parent idle; the runtime reports no active work while children run) | `SUBAGENTS` |
| 7 | shells and not processing | `WATCHING` |
| 8 | not started | `READY` |
| 9 | otherwise | `YOUR TURN` |

Within the extension only `session.error` leads to `ERROR`; failed tool calls
never do. (The tmux side additionally shows `ERROR` for a dead pane, 6.2.)

#### 5.4.3 Derived values

- `since`: startedAt when the label is `WORKING`, `SUBAGENTS` or `WATCHING`;
  doneAt when `YOUR TURN`; otherwise undefined (`NEEDS YOU`, `ERROR`, `READY`).
- `took`: only when the label is `YOUR TURN` and both doneAt and startedAt are
  defined: `max(0, doneAt − startedAt)`; otherwise undefined.
- **Settling rule**: whenever an operation changes the label from anything else
  to `YOUR TURN`, doneAt becomes the operation's time (event time for
  `accept`; the `timestamp` argument for the setters, where `null` means
  "unknown" and leaves doneAt undefined).
- Event time: if `timestamp` is absent, the current time; else parsed as a
  date; a non-finite result throws a `TypeError` whose message contains
  `Invalid dashboard event timestamp`. Seconds = floor(milliseconds / 1000).
  Time is computed only where needed. For run starts (row 5), `session.idle`
  and `abort` it is computed before the event changes anything, so a bad
  timestamp leaves the state untouched; for other events it is computed only
  after applying them and only if the label just became `YOUR TURN`, in which
  case the throw leaves the applied changes but no doneAt.

#### 5.4.4 Setters (snapshot inputs)

- `setActivity(active, timestamp = now seconds)`: if active, set startedAt to
  timestamp only when startedAt is still undefined (null keeps it undefined)
  and clear doneAt; set working = active; if inactive, call
  `setProcessing(false)`; if active, started = true; then apply the settling
  rule with timestamp. Note startedAt is **not** cleared when a run ends; it is
  only replaced by the run-start rules in 5.4.5, so background activity that
  resumes after an idle keeps the original start.
- `setProcessing(p)`: processing = p; when false, tools is cleared.
- `setTasks(tasks, timestamp = now seconds)`: agents = every task with
  `type === "agent"` and `status === "running"`, mapped toolCallId →
  executionMode (replacing the previous map); shells = some task has
  `type === "shell"`, `status === "running"` and `attachmentMode === "attached"`
  (detached shells, other statuses and other types never count); then apply
  the settling rule with timestamp.

#### 5.4.5 Event transitions (`accept`)

`data` defaults to `{}`. Let `kind` and `action` be the first and second
dot-separated parts of `type`.

| Order | Event | Effect |
|---|---|---|
| 1 | `kind` ∈ {`elicitation`, `exit_plan_mode`, `permission`, `auto_mode_switch`, `user_input`, `session_limits_exhausted`} and `data.requestId` truthy | `requested` without truthy `data.resolvedByHook`: add `kind:requestId` to pending. `completed`: remove it. Other actions: nothing. Stop. Applies to child-agent events too. Keys are per kind, so a `permission` and an `elicitation` with the same id are independent |
| 2 | `subagent.started` (any agentId) | agents[data.toolCallId] = data.executionMode. Stop |
| 3 | `subagent.completed`, `subagent.failed` (any agentId) | remove agents[data.toolCallId]. Stop |
| 4 | any event with truthy `agentId` | ignored (a child cannot start or finish the parent's turn) |
| 5 | `user.message`, `assistant.turn_start` | If not working, or the event is `user.message` with `data.delivery` `idle` or `queued`: startedAt = event time and clear tools. Then always: doneAt undefined, started, working, processing = true, failed = false. A steering message (other delivery) or a model turn during a run keeps the run's start |
| 6 | `tool.execution_start` | processing = true; tools[data.toolCallId] = (`data.toolName === "read_agent"` and `data.arguments.wait === true`) |
| 7 | `tool.execution_complete` | remove tools[data.toolCallId] (success flag irrelevant) |
| 8 | `assistant.idle` | `setProcessing(false)` |
| 9 | `session.idle` | `setActivity(false, event time)`; if `data.aborted`, clear pending |
| 10 | `session.error` | started = true, working = false, `setProcessing(false)`, failed = true, doneAt undefined |
| 11 | `abort` | `setActivity(false, event time)`, failed = false, clear pending |
| 12 | anything else (e.g. `assistant.turn_end`) | no effect |

After applying, the settling rule runs using the event time.

Worked examples the implementation MUST reproduce: a run started at 100 with
steering at 150 that idles at 352 reports `YOUR TURN`, since 352, took 252; a
new `assistant.turn_start` at 400 (not working) and idle at 405 reports took 5;
an input request makes since undefined and its completion restores the run
start; an input completed at 170 after the parent already idled settles at 170;
`abort` at 220 after an error settles at 220.

### 5.5 Runtime (`extension.mjs`)

Module-level state: current state object; an event buffer; `initializing`
(initially true); a revision counter (0); last published key and folder; a
`trackingFailed` flag (false); the in-flight synchronisation promise; a retry
timer handle; `retryDelay` = 1000 ms; the session.

**Event handler** (`onEvent`): if disabled, return. Increment revision. If
initializing or trackingFailed, append the event to the buffer and return.
Otherwise `accept` and publish; any thrown error goes to *report*. Then, if the
type is `subagent.started`/`subagent.completed`/`subagent.failed` (any
agentId), or the event has no agentId and its type is `session.idle`,
`assistant.idle`, `abort` or `session.background_tasks_changed`, start a
*reconcile* (not awaited).

**Synchronise** (single-flight: a call while one is running returns the
running promise; the slot is cleared when it settles):
1. initializing = true; build a fresh state object.
2. `await getEvents()` and `accept` each event in order.
3. Concurrently await activity, pending permissions, isProcessing, tasks list.
4. On the fresh state: `setActivity(hasActiveWork, null)` (idle events are not
   persisted, so history cannot provide a settle time); `setProcessing(processing)`;
   `setTasks(tasks, null)`; for each pending permission item, accept a synthetic
   `{ type: "permission.requested", data: { requestId } }`.
5. Replay buffered events in arrival order, then empty the buffer.
6. Swap in the fresh state; trackingFailed = false; publish; initializing =
   false; cancel any retry timer; retryDelay = 1000.
7. `await` folder publish.
On any error in steps 1–6: empty the buffer and *report* the error
(initializing stays true, so later events buffer until a successful retry).

**Reconcile**: remember the revision; concurrently await activity,
isProcessing and tasks list. If the revision changed meanwhile, or
initializing or trackingFailed is set, discard the result (an old answer must
never finish a newer turn). Otherwise `setActivity(hasActiveWork)`,
`setProcessing(processing)`, `setTasks(tasks)` (both with the current time)
and publish. Errors go to *report*.

**Report(error)**: trackingFailed = true; log `Environment dashboard update
failed:` plus the error to stderr; attempt a publish (which shows `UNKNOWN`),
logging a message containing `could not display UNKNOWN` if that throws. If a
session exists, the extension is enabled and no retry timer is pending:
schedule *synchronise* after `retryDelay` ms with `setTimeout`, call `unref()`
on the handle (so it never keeps the process alive), and double `retryDelay`
up to a cap of 30000 ms. The timer callback clears the handle before
synchronising. Backoff sequence: 1000, 2000, 4000, … 30000; reset to 1000 on
success.

**Startup**:
1. `await joinSession({ onEvent })`. If it throws: *report* the error (shows
   `UNKNOWN` if enabled; no retry because there is no session) and rethrow, so
   loading the module fails with the original error message.
2. If enabled: register a one-time `exit` handler (below), one-time `SIGTERM`
   and `SIGINT` handlers that call `process.exit(0)`, then `await`
   *synchronise*. Module evaluation completes only after the first
   synchronisation attempt finishes (top-level await).

**Exit cleanup**: cancel the retry timer; read `#{@env-dashboard-owner}` of the
pane with `display-message -p`. Only if it equals this PID (another Copilot
may have taken over the pane), issue one tmux call that unsets (`-pu`)
`@env-copilot-state`, `@env-copilot-since`, `@env-copilot-took`,
`@env-session-dir`, `@env-dashboard-owner`, then `refresh-client -S`. Errors
are logged with a message containing `cleanup failed`.

The extension never polls: lifecycle events, the initial snapshot, and
event-triggered reconciles are the only inputs.

## 6. Dashboard tmux configuration (`terminal/ai-agents.conf`)

Every setting in this file targets the `ai-agents` session explicitly
(`set -t ai-agents …`, `set-hook -t ai-agents …`) except the two mouse key
bindings, which are server-wide root-table bindings guarded so that they only
change behaviour inside `ai-agents`. Sourcing it repeatedly is idempotent.

### 6.1 Session options

| Option | Value |
|---|---|
| `status` | `5` (five status lines) |
| `status-position` | `top` |
| `status-interval` | `1` (re-render every second) |
| `set-titles` | `on` |
| `set-titles-string` | `🫲 AI Agents 🫱` |
| `status-style` | `bg=colour235,fg=colour252` |

### 6.2 Derived session user options (formats)

Formats are evaluated per pane (the active pane of the window being drawn).
Tests override several of these options, so the names are contracts. The
three formats `@hand-status-activity`, `@hand-status-timer` and
`@hand-status-title` MUST test the running program with the literal token
`#{pane_current_command}` (tests substitute it with `copilot`).

| Option | Evaluates to |
|---|---|
| `@hand-status-idle-pattern` | Regular expression matching exactly the idle label set (section 2.1), anchored at both ends |
| `@hand-status-activity` | `ERROR` if the pane is dead; else if the pane's current command is `copilot`: when `@env-copilot-state` is non-empty, `YOUR TURN` if it matches the idle pattern, else the state verbatim (`UNKNOWN`, `NEEDS YOU`, …); when empty or unset, `COPILOT`; else if the current command is exactly one of `fish`, `zsh`, `bash`, `sh`, `dash`, `ksh`: `READY`; else `WORKING` (some other foreground program) |
| `@hand-status-idle` | True (`1`) when the activity matches the idle pattern (i.e. is `YOUR TURN`) |
| `@hand-status-state` | `WAITING` when idle and `@env-waiting-reason` is non-empty; else the activity |
| `@hand-status-state-style` | Style for the state (6.4) |
| `@hand-status-now` | `%s`, expanded through strftime to the current Unix seconds |
| `@hand-status-age` | now − `@env-copilot-since` (integer) |
| `@hand-status-span` | `@env-copilot-took` when the state is `YOUR TURN`, else the age |
| `@hand-status-seconds` | span clamped below at 0 (a clock that moved backwards shows `0s`) |
| `@hand-status-duration` | Human duration of seconds (6.5) |
| `@hand-status-clock` | Local `HH:MM` (24-hour, zero padded) of `@env-copilot-since`; strftime escapes must survive nested expansion |
| `@hand-status-timer` | Timer text (6.5) |
| `@hand-status-title` | Title text (6.6) |
| `@hand-status-title-width` | floor(`client_width` / 2) − 49 |
| `@hand-status-cell` | One dashboard entry (6.3) |

### 6.3 Status layout

Five lines; each shows the left-hand environment then the right-hand one:

| Status line (`status-format[n]`) | Left cell | Right cell | Extra |
|---|---|---|---|
| 0 | window 1 | window 6 | right-aligned **hotkeys** button |
| 1 | window 2 | window 7 | |
| 2 | window 3 | window 8 | |
| 3 | window 4 | window 9 | |
| 4 | window 5 | window 10 | |

A cell exists only if a window with that index exists. A cell is, in order:
1. Start of a clickable range `#[range=window|<index>]`.
2. If the window is active: `#[bg=colour238 bold]` (highlight lasts to the end of the cell).
3. A space, then `<index>:` left-justified to width 4, then the window name
   left-justified to width 14, then a space.
4. The state style (6.4), the state left-justified to width 10, a space, the
   timer left-justified to width 13.
5. `#[fg=colour252]`, a space, the title truncated to the title width and then
   padded to exactly that width.
6. `#[default]#[norange]`.

For example a `YOUR TURN` window shows the substring
`#[fg=colour226]YOUR TURN  4m12s @09:46 ` (state padded to 10, a space, timer
padded to 13).

Hotkeys button (status line 0 only, after the two cells): right-aligned, in a
user range named `keys` (`range=user|keys`), style `bg=colour31 fg=colour231 bold`,
text ` hotkeys ` (space-padded), followed by ending the range and resetting style.

### 6.4 State colours

| State | Foreground |
|---|---|
| `WATCHING` | `colour117` |
| `SUBAGENTS` | `colour141` |
| `NEEDS YOU` | `colour214` |
| `ERROR` | `colour203` |
| `WORKING` | `colour75` |
| `YOUR TURN` | `colour226` |
| `READY`, `COPILOT`, `UNKNOWN`, `WAITING`, anything else | `colour244` |

Each is emitted as `#[fg=colourNNN]` immediately before the state text.

### 6.5 Timer and duration

Duration of `s` seconds (integer division, no zero padding):

| Range | Format | Examples |
|---|---|---|
| s < 60 | `<s>s` | `0s`, `59s` |
| s < 3600 | `<s/60>m<s mod 60>s` | `1m0s`, `59m59s` |
| s < 86400 | `<s/3600>h<(s/60) mod 60>m` | `1h0m`, `23h59m` |
| otherwise | `<s/86400>d<(s/3600) mod 24>h` | `1d0h`, `1d1h` |

Timer (empty unless the pane's current command is `copilot` **and**
`@env-copilot-since` is non-empty):
- activity `WORKING`, `SUBAGENTS` or `WATCHING`: the duration of the age (run
  elapsed time), e.g. `1m23s`.
- state `YOUR TURN`: when `@env-copilot-took` is non-empty, the duration of
  `took`, a space, `@`, the clock; otherwise just `@` and the clock (chats on
  an older extension). Example `4m12s @09:46`.
- other idle states (i.e. `WAITING`): the duration of the age followed by
  ` ago`, e.g. `1m23s ago` (time since the turn finished).
- anything else (`NEEDS YOU`, `ERROR`, `READY`, `COPILOT`, `UNKNOWN`): empty.

The display advances every second because `status-interval` is 1 and "now" is
re-evaluated at each render; no process writes timer values.

### 6.6 Title

Concatenation of:
1. When idle and a waiting reason exists: `Waiting on: `, the reason with every
   `#[` replaced by `# [` (so user text cannot inject styles), then ` | `.
2. When the current command is `copilot`: the pane title with a trailing
   `GitHub Copilot` removed if it is the entire title or is preceded by ` - `.
   Examples (pane title → shown): a bare `GitHub Copilot` → empty;
   `Fix flaky test - GitHub Copilot` → `Fix flaky test`;
   `GitHub Copilot setup - GitHub Copilot` → `GitHub Copilot setup` (only the
   suffix goes); `GitHub Copilotish` → unchanged (no exact suffix match).
   Non-Copilot panes contribute nothing.

### 6.7 Waiting reasons

A waiting reason is a local reminder attached to an idle chat; it is not a
scheduler and nothing acts on it automatically.

**Automatic clearing** — session hook `after-set-option[71]` on `ai-agents`:
after any option change, evaluated for the pane whose option changed, if that
pane has a non-empty `@env-waiting-reason` and either its raw
`@env-copilot-state` does not match the idle pattern or its
`@env-waiting-owner` differs from its `@env-dashboard-owner`, unset both
`@env-waiting-reason` and `@env-waiting-owner` on that pane only. Hence work
resuming (`WORKING`, `SUBAGENTS`), input (`NEEDS YOU`), `ERROR`, `UNKNOWN`, or a
new Copilot process taking over the pane all clear it; switching between idle
labels (e.g. `YOUR TURN` → `DECIDE`) keeps it; other panes are untouched.
Because the extension publishes pane options, this works for chats already
running.

**Right-click entry** — root binding `MouseDown3Status`, when the clicked
status entry belongs to session `ai-agents`:
1. Select the clicked window (`select-window -t =`).
2. If that window's chat is not idle, show a status message that reasons may
   only be set on idle chats; stop.
3. Otherwise open a command prompt labelled `Waiting on (empty clears)` whose
   initial text is the current reason. The response is used literally: commas,
   quotes, semicolons, `#{…}`, `#[…]` and `$(…)` are stored verbatim and never
   executed or expanded, and resubmitting the unchanged text keeps it
   byte-identical.
4. On submit, re-check idleness. If still idle, first set `@env-waiting-owner`
   to the pane's current `@env-dashboard-owner`, then set `@env-waiting-reason`
   to the response (an empty response leaves an empty value, which counts as no
   reason and the state returns to `YOUR TURN`). If no longer idle, store
   nothing and show a status message saying the chat stopped being idle so the
   reason was not saved.
5. Escape cancels without changes.

When the click is outside `ai-agents`, the binding reproduces tmux's default
window menu (6.8).

### 6.8 Mouse bindings

**Left click** — root binding `MouseDown1Status`:
- In session `ai-agents` with the click on the `keys` range: open the
  shortcuts menu (below).
- Everywhere else, including clicks on a cell's `window|<index>` range: tmux's
  default (`switch-client -t =`), which selects the clicked window. Clicking
  terminal row 2 (`status-format[1]`) at column 10 selects window 2.

**Shortcuts menu**: opened with the option that keeps it open after the button
is released (`display-menu -O`); a second click on the button closes it.
Title ` Digits shortcuts ` centred in `colour117`; placed at the right edge
(`-x R`) on the status line (`-y S`); rounded border; menu style
`fg=colour252,bg=terminal`; border style `fg=colour240,bg=terminal`; selected
item style `fg=colour235,bg=colour117`. No item has a key letter. Rows, in
order (description left-justified to 30 columns after one leading space, then
the key hint left-justified to 24 columns; ASCII only, because terminals and
tmux disagree on the width of ⌘ and ⇧):

| # | Enabled | Description | Key hint | Action |
|---|---|---|---|---|
| 1 | yes | Next chat needing attention | ``Cmd+` `` | `run-shell` launcher `--next-attention` |
| 2 | yes | Open newest session Markdown | `Cmd+Shift+M` | `run-shell` launcher `--markdown "#{pane_id}" --client "#{client_name}"` |
| 3 | yes | Next window | `Cmd+Shift+]` | `next-window` |
| 4 | yes | Previous window | `Cmd+Shift+[` | `previous-window` |
| 5 | yes | Last window | `Cmd+;` | `last-window` |
| — | | separator | | |
| 6 | no (info) | Window 1-10 | `Cmd+1 ... Cmd+9, Cmd+0` | none |
| 7 | no (info) | Switch chat | `Click its entry` | none |
| 8 | no (info) | Set waiting reason | `Right-click an idle chat` | none |
| 9 | no (info) | Open a link | `Shift+Cmd+click` | none |

Since rows 6–9 are disabled, pressing Up then Enter in a freshly opened menu
runs **Last window**. Launcher actions run as `exec "$HOME/.local/bin/ai-agents" …`
through `run-shell` in the foreground (not `-b`), so consecutive invocations
are serialised by tmux.

**Right click outside `ai-agents`**: show tmux's standard window menu at the
window (`-x W -y W`), titled `<index>:<name>` centred, with items: Swap Left
(`l`, disabled when the session has one window), Swap Right (`r`, same
condition), Swap Marked (`s`, disabled unless a marked pane exists),
separator, Kill (`X`), Respawn (`R`, kills and respawns), Mark/Unmark (`m`,
label depends on whether the pane is marked), Rename (`n`, prompt pre-filled
with the window name), separator, New After (`w`), New At End (`W`).

## 7. Optional terminal fragments (never installed automatically)

### 7.1 Global include `terminal/ai-agents.tmux.conf`

For merging into the user's own tmux configuration. Sets global `mouse on` and
global `allow-passthrough on` (lets Copilot CLI image previews reach Ghostty);
adds global hook `session-created[50]` that sources `~/.tmux/ai-agents.conf`
when the new session is named `ai-agents`; and at load time sources the same
file if a session named exactly `ai-agents` already exists. The launcher does
not depend on this include.

### 7.2 Shortcut bindings `terminal/ai-agents-shortcuts.tmux.conf`

Intended to be copied to `~/.tmux/ai-agents-shortcuts.conf` and sourced from
`~/.tmux.conf`. It defines **server-wide** `user-keys[180]` … `user-keys[194]`
and root-table (`-n`) bindings `User180` … `User194`. Each binding acts only
when the client's current session is named `ai-agents` **and** its
`@ai-agents-managed` is `1`; otherwise the key does nothing. Ordinary keys and
existing bindings such as Meta/Alt chords (e.g. Alt+1 sent as ESC `1`) keep
working.

| User key | Byte sequence (ESC = `\e`) | Ghostty key | Action |
|---|---|---|---|
| 180–189 | `\e[5;31001~` … `\e[5;31010~` | Cmd+1 … Cmd+9, Cmd+0 | select window 1 … 10 of the current session by exact index (`:=N`) |
| 190 | `\e[5;31011~` | Cmd+Shift+] | `next-window` (wraps) |
| 191 | `\e[5;31012~` | Cmd+Shift+[ | `previous-window` (wraps) |
| 192 | `\e[5;31013~` | Cmd+; | `last-window` |
| 193 | `\e[5;31014~` | Cmd+` | run launcher `--next-attention` |
| 194 | `\e[5;31015~` | Cmd+Shift+M | run launcher `--markdown "#{pane_id}" --client "#{client_name}"` |

In general user key `180+k` (k = 0…14) is the sequence `\e[5;<31001+k>~`.
Launcher actions use `run-shell` in the foreground exactly as in the
shortcuts menu.

### 7.3 Ghostty key bindings `terminal/ghostty-keybindings.conf`

One line per binding, each of the exact form `keybind = <key>=<action>`:
- `cmd+enter` → `unbind` (frees Cmd+Enter for the terminal application).
- `cmd+1` … `cmd+9`, `cmd+0`, `cmd+shift+bracket_right`,
  `cmd+shift+bracket_left`, `cmd+semicolon`, `cmd+backquote`, `cmd+shift+m` →
  `csi:5;31001~` … `csi:5;31015~` respectively (Ghostty then sends ESC `[`
  followed by that text). Each key appears exactly once.

These replace Ghostty's tab shortcuts, its Cmd+0 font-size reset, and macOS
Cmd+` window cycling.

### 7.4 Ghostty bell `terminal/ghostty.conf`

Three Ghostty settings, one per line:

| Setting | Value | Purpose |
|---|---|---|
| `bell-audio-volume` | `0.25` | quarter volume |
| `bell-features` | `attention,audio,no-system` | request attention and play audio, skip the system alert |
| `bell-audio-path` | `/System/Library/Sounds/Glass.aiff` | the built-in Glass sound |

Effect: the macOS Glass sound at a quarter volume plus window attention,
without the system alert sound.

## 8. Copilot settings example `copilot/settings.json`

A JSON object for users to review and merge by hand; the installer never
writes `~/.copilot/settings.json`. Top-level keys: `beep` true, `experimental`
true (needed by the dashboard), `theme` `"github"`, and `footer`, an object of
booleans: `showModelEffort`, `showDirectory`, `showBranch`,
`showContextWindow`, `showQuota`, `showAiUsed`, `showAgent`,
`showCodeChanges`, `showSandbox`, `showYolo`, `showCiStatus`, `showCustom` all
true, and `showUsername` false. Formatted with 2-space indentation.

## 9. Installer `install.py`

**Importable interface (MUST).** `install.py` is also imported as a module by
`context_install.py` and its tests. It MUST expose, at module level and with
the exact names, signatures and plan structure given in `20-context.md` §3:
`digest`, `checked_path`, `atomic_write`, `execute`, and `show_plan`. The
workbench planner and executor in this section MUST use that same plan
structure, so a single `execute` serves both installers. Importing the module
MUST have no side effects (the command line runs only under `__main__`).

### 9.1 Command line

`python3 install.py [--apply] [--uninstall] [--home PATH]`

| Flag | Effect |
|---|---|
| (none) | Preview installation: print the plan, then `Preview only. Re-run with --apply to make changes.`; write nothing (no lock, no directories) |
| `--apply` | Perform the previewed changes |
| `--uninstall` | Preview removal (combine with `--apply` to remove) |
| `--home PATH` | Destination home (default: the user's home); `~` is expanded and the path made absolute (symlinks not resolved). Useful for trials |

Prerequisites (checked for install previews and installs, **not** for
uninstall): the platform must be macOS (`Darwin`), else fail with a message
that only macOS is supported; `tmux`, `node` and `copilot` must be on
`PATH`, else fail listing the missing names comma-separated after a request to
install them first.

Exit status: 0 on success (`main` returns 0); on validation, OS or rollback
errors print `Dashboard installer: <error>` to stderr and exit 1; argument
errors exit 2.

With `--apply`: open the home directory itself read-only with no-follow and
take a **non-blocking** exclusive `flock` on that descriptor (no lock file is
created; a concurrent installer fails immediately with an OS error). Under the
lock: compute the plan, print it, execute it. Then print:
- install: the text `Installed. Launch from your terminal:` then a space and
  the absolute launcher path under the target home, and a second line saying no session was started and existing Copilot chats
  need an idle restart or reload;
- uninstall: a line saying unchanged owned files were removed and running
  sessions were not stopped, and a line advising an idle reload/restart of
  Copilot to unload the extension.

### 9.2 Managed set

- Files: the five installed files of section 1 with their modes (installer
  table order: `ai-agents`, `md-view`, `ai-agents.conf`, `extension.mjs`,
  `state.mjs`). Sources are read from the repository directory containing
  `install.py` (resolved).
- Receipt: `.local/state/digits/dashboard.json`, mode `0600`.
- Managed directories: the ten environment directories plus every ancestor
  (below home) of the five files and the receipt: `.local`, `.local/bin`,
  `.local/state`, `.local/state/digits`, `.tmux`, `.copilot`,
  `.copilot/extensions`, `.copilot/extensions/env-dashboard` (18 in total).
- Never touched: `~/.tmux.conf`, `~/.tmux/ai-agents-shortcuts.conf`, Ghostty
  configuration, `~/.copilot/settings.json`, MCP configuration, repositories.
  The installer never starts sessions or chats and never authenticates.

### 9.3 Path safety

Every path is resolved under home component by component. If any component
(including the final one) is a symlink: fail with a message containing
`Refusing symlink:` and the path. If a non-final component exists but is not a
directory: fail with `Parent is not a directory:`. The home itself must be an
existing directory that is not a symlink, else fail.

### 9.4 Receipt format

JSON, `sort_keys`, 2-space indentation, trailing newline:

| Key | Type | Meaning |
|---|---|---|
| `version` | integer `1` | Schema version |
| `files` | object | Installed-relative path → `{ "sha256": 64 lowercase hex of the installed bytes, "mode": integer permission bits (420 = 0644 or 493 = 0755) }` |
| `directories` | array of strings, sorted | Managed directories this installer created (cumulative across runs) |

Validation when reading (any failure aborts before changes): the receipt path
must be a regular file if present; JSON must parse; top level an object;
`version` exactly 1; `files` an object whose keys are a **subset** of the five
managed files (older receipts may own fewer — see adoption); `directories` a
list of strings, each one of the 18 managed directories; otherwise fail with
`Unrecognized installation receipt:`. Each file record must be an object with
a 64-character lowercase-hex `sha256` and an integer (not boolean) `mode` of
0644 or 0755, else fail with `Invalid file record in receipt:`.

### 9.5 Planning

A plan has `create` (directories, ordered), `writes` (ordered map path →
(bytes, mode)), `remove` (ordered paths) and `prune` (directories).

Common steps: validate home; read the receipt; if there is one, every recorded
directory that exists must be a real directory reached without symlinks,
otherwise fail (`Expected an installed directory:` or the symlink message).

Uninstall without a receipt: empty plan (nothing is removed, even files that
look like ours).

Per managed file (skipping, when uninstalling, files the receipt does not own):
- If it exists it must be a regular file (`Destination is not a regular file:`).
- If it exists and is not owned by the receipt: fail with
  `Existing unowned file; merge manually instead: <path>` — even when its
  contents are identical to the source.
- If it is owned and exists, its SHA-256 and permission bits must match the
  record, else fail with `Locally modified file; preserving it: <path>`
  (this blocks both update and removal).
- Install: record the source's hash and the declared mode; schedule a write if
  the target is missing, its bytes differ, or its mode differs. An owned file
  that was deleted is simply reinstalled.

Uninstall plan: `remove` = owned files that currently exist (receipt order),
then the receipt itself; `prune` = the receipt's directories; no writes or
creates.

Install plan: every managed directory must be absent or a real directory
(`Expected a directory:`); `create` = the absent ones sorted by depth then
name; the new receipt lists all five files and `directories` = previously
recorded ∪ newly created, sorted; the receipt is appended to `writes` when it
is missing, its bytes differ, or its mode is not 0600. A second install over an
unchanged installation has empty `writes` and `create`.

**Adoption**: when a receipt from an older release lacks a file, the installer
installs and records that file if it is absent on disk, but refuses (unowned)
if something already exists there. Uninstall with such a receipt removes only
the files it owns and leaves the foreign file.

### 9.6 Plan output

Lines, grouped in this order, each with the absolute path:
`CREATE directory <path>`, `WRITE <path>`, `REMOVE <path>`,
`REMOVE directory if empty <path>`. If `create`, `writes` and `remove` are all
empty, print `No file changes needed.`

### 9.7 Execution, atomicity and rollback

1. Create each `create` directory (re-checked for symlinks) with mode `0700`
   (subject to umask), remembering it.
2. For each path in `writes` then `remove`, re-check it, journal its prior
   bytes and mode (or "absent"), then write atomically or unlink it.
3. Atomic write: create a temporary file named with prefix `.digits-` in the
   destination directory, write and flush the bytes, set the exact mode on the
   descriptor, rename over the destination; delete the temporary file if
   anything fails.
4. On any OS or validation error in steps 1–2: walk the journal backwards,
   restoring prior contents and mode with atomic writes or deleting files that
   did not exist before; then remove the directories created in step 1 if they
   are empty (deepest first). If any rollback step fails, raise a combined
   error `<original>; rollback incomplete: <details>` (exit 1); otherwise
   re-raise the original error. A failed fresh install leaves home exactly as
   before; a failed update restores the previous owned files and receipt.
5. After success, prune `prune` directories deepest first: skip missing ones,
   remove empty ones, and for non-empty ones print
   `KEEP non-empty directory <path>` and continue. Pre-existing directories are
   never in the receipt, so they are never removed; environment directories
   containing work are kept.

## 10. Timing and concurrency summary

| Item | Value |
|---|---|
| Status refresh | every 1 s (`status-interval 1`), plus immediate `refresh-client -S` after each publish |
| Extension tmux call timeout | 2000 ms |
| Extension retry backoff | 1000 ms doubling to a 30000 ms cap; reset on success; timers are `unref`'d |
| Synchronisation | single-flight; events during it are buffered and replayed |
| Reconcile staleness | results discarded if any event arrived meanwhile |
| Launcher lock | blocking exclusive flock on `~/Library/Caches/env-sync/ai-agents.lock`, ensure step only |
| Installer lock | non-blocking exclusive flock on the home directory descriptor, apply only |

## 11. Acceptance tests

### 11.1 Harness requirements

- **Python suites** (`unittest`): each test uses a fresh temporary directory as
  the home passed to the installer (`--home` or the planning/execution API) or
  patched into the launcher; nothing touches the real home.
- **Launcher suite**: skipped when `tmux` is not installed. Each test creates
  the ten environment directories in a temporary home, starts an isolated tmux
  server with a unique socket name (`tmux -L <unique> -f /dev/null`, so no user
  configuration loads) holding an unrelated session `unrelated` running
  `/bin/sh`, and kills that server on cleanup. The launcher's hooks are patched
  so that home is the temporary directory, the configuration path is the
  repository's `terminal/ai-agents.conf` (or the installed copy where stated),
  fish is replaced by `/bin/sh` (so no fish is required and panes show
  `READY`), and tmux/session-listing calls go to the isolated socket.
- **Copilot simulation**: no real Copilot is started. Tests set pane options
  directly and replace the literal `#{pane_current_command}` token in the
  activity, timer and title formats with `copilot`.
- **Real client**: where keys or mouse clicks are needed, a tmux client is
  attached through a pseudo-terminal sized 240 columns × 40 rows with
  `TERM=xterm-256color`; initial output is drained; keystrokes are written as
  bytes (Ghostty sequences are read from `terminal/ghostty-keybindings.conf`
  by matching the line prefix `keybind = <key>=csi:` and prefixing ESC `[`);
  mouse input uses SGR reports (`ESC [ < button ; column ; row M` then `m`);
  status messages are detected by reading the client's terminal output.
  Waits poll for up to 4 s.
- For tests running launcher actions from tmux bindings, the installer installs
  into the temporary home and the isolated server's global environment `HOME`
  (and, for the Markdown test, `PATH` and `VSCODE_IPC_HOOK_CLI`) is set with
  `set-environment -g`.
- **VS Code simulation**: a fake executable named `code` placed first on
  `PATH` records its arguments (and the value of `VSCODE_IPC_HOOK_CLI`) to a
  marker file.
- **Extension suite** (`node:test`): each scenario copies `extension.mjs` and
  `state.mjs` into a temporary directory together with a fake package
  `node_modules/@github/copilot-sdk` (ES module, exporting `./extension`) whose
  `joinSession` delegates to a scenario-controlled stub. A driver script runs
  in a child Node process with `TMUX=/synthetic-tmux,1,0` and `TMUX_PANE=%1`;
  before importing the extension it replaces the global
  `setTimeout`/`clearTimeout` with recorders (timers fire only when the
  scenario triggers them; requested delays are recorded), replaces
  `execFileSync` of `node:child_process` (then synchronises builtin ESM
  exports) with a recorder that answers `display-message` with the process PID
  and records each state publish as `{label, since[, took]}` (took only when
  non-empty) and each folder publish (`null` for an unset). The stubbed
  session's history initially holds one `user.message` at Unix second 100,
  activity is active, processing is true, tasks and pending requests are empty
  unless a scenario says otherwise; emitted `user.message` events are appended
  to history. "Settle" means letting pending promises run. The driver prints
  a JSON summary; the test asserts on it and on stderr.

### 11.2 State machine (`state.mjs`)

1. Given a fresh state, then label is `READY`. When `user.message` then
   `assistant.turn_end` arrive, then `WORKING`; after `session.idle`, `YOUR TURN`;
   `setActivity(true)` gives `WORKING`; `setActivity(false)` gives `YOUR TURN`.
2. Given a turn has started, when `permission.requested` and
   `elicitation.requested` both use request id `one` and only the permission
   completes (and activity is set true), then `NEEDS YOU`; when the elicitation
   completes, then `WORKING`.
3. Given a fresh state, when a `permission.requested` with `resolvedByHook`
   true arrives, then the label stays `READY`.
4. Given a running turn, when a child (`agentId` set) sends `session.idle`, then
   still `WORKING`; when the child sends `user_input.requested`, then
   `NEEDS YOU`; when it completes, then `WORKING`.
5. Given a run started at 100 and a `task` tool call `spawn` at 101, when a
   child `subagent.started` (sync, toolCallId `spawn`) arrives at 102, then
   `SUBAGENTS` with since 100; when an unrelated `bash` tool starts, then
   `WORKING`; when it completes, `SUBAGENTS`; when the subagent completes,
   `WORKING`; after the `spawn` tool completes and a new model turn starts at
   107, since is still 100; `session.idle` at 110 gives `YOUR TURN` with since 110.
6. Given a run at 100 and two background subagents, then `WORKING`, also after
   `assistant.turn_end` and after a child's `assistant.idle`; when the parent's
   `assistant.idle` arrives, then `SUBAGENTS`; a new parent model turn gives
   `WORKING` with since 100; after the parent idles again and one agent
   completes, still `SUBAGENTS`; when the other fails, `WORKING`;
   `setActivity(false, 107)` gives `YOUR TURN` since 107.
7. Given a run at 100 and a running background agent from a task snapshot, when
   a `read_agent` call with `wait: false` starts, then `WORKING`; after it
   completes and a `read_agent` with `wait: true` starts, then `SUBAGENTS`; a
   child permission request gives `NEEDS YOU` and its completion `SUBAGENTS`;
   completing the wait gives `WORKING`; `session.error` gives `ERROR`.
8. Given a run at 100 with a stale background subagent, when processing is set
   false and a task snapshot lists a different running agent, then
   `SUBAGENTS`; when the snapshot lists only agents with status completed, idle,
   cancelled or failed plus a running shell without attachment and a running
   `client` task, then `WORKING`; `setActivity(false, null)` gives `YOUR TURN`
   with since undefined.
9. Given a running turn, when a tool completes with `success: false`, then
   still `WORKING`; when `session.error` then `session.idle` arrive, then
   `ERROR`; a new `user.message` gives `WORKING`.
10. Given a pending permission during a turn, when `abort` arrives, then
    `YOUR TURN`; a new `user.message` gives `WORKING`.
11. Given `user.message` at 100, a model turn at 102, turn end at 110, a
    steering message at 112 and a model turn at 114, then since is 100; a
    permission request at 120 makes since undefined; its completion at 150
    restores 100; a child `session.idle` at 160 keeps 100; the parent's
    `session.idle` at 180 gives `YOUR TURN` since 180; `setActivity(false, 200)`
    and another `session.idle` at 210 keep since 180; a `user.message` at 300
    gives since 300.
12. Given history `user.message` (delivery idle) at 100, model turn 102,
    `user.message` (delivery queued) at 200, model turn 202, when
    `setActivity(true, null)` then since is 200; when `setActivity(false, null)`
    then `YOUR TURN` with since undefined.
13. Given a run at 100 that idles at 200, when `setActivity(true, 205)`, then
    `WORKING` with since 100; `setActivity(false, 300)` gives `YOUR TURN` since 300.
14. Given a run at 100 with a `user_input.requested` at 120, when the parent
    idles at 150, then `NEEDS YOU`; when the input completes at 170, then since
    is 170. Given then a message at 200 and `session.error` at 210, since is
    undefined; `abort` at 220 gives since 220.
15. Given a fresh state, when a `user.message` with timestamp `not-a-timestamp`
    is accepted, then a `TypeError` mentioning `Invalid dashboard event timestamp` is thrown.
16. Given a run at 100 and two attached running shells from a snapshot at 110,
    then `WORKING`; parent `assistant.idle` at 120 gives `WATCHING` since 100; a
    model turn at 130 gives `WORKING`; `session.idle` at 140 gives `WATCHING`; a
    snapshot with one shell at 150 keeps `WATCHING`; a snapshot whose shell is
    completed at 160 gives `YOUR TURN` since 160; an empty snapshot at 170 keeps
    since 160.
17. Given an idle parent watching one attached shell, a permission request
    gives `NEEDS YOU`, its completion `WATCHING`, `session.error` gives `ERROR`,
    `abort` returns to `WATCHING`; a snapshot holding only a detached running
    shell and attached shells with status completed, cancelled, failed or idle
    at 160 gives `YOUR TURN` since 160.
18. Given a run at 100 then snapshot-style updates (activity false with null
    time, processing false, attached shell with null time), then `WATCHING`
    since 100; an empty task snapshot with null time gives `YOUR TURN` with
    since undefined.
19. Given a run at 100 with steering at 150, then took is undefined; idle at
    352 gives `YOUR TURN`, since 352, took 252; a model turn at 400 and idle at
    405 give took 5; a message at 500 followed by `setActivity(false, null)`
    gives `YOUR TURN` with took undefined.

### 11.3 Extension runtime (`extension.mjs`)

20. For each initialisation step failing — history (fails twice), activity,
    pending permissions, isProcessing, tasks (each once), and the first
    non-`UNKNOWN` publish — the first recorded publish is `UNKNOWN`, stderr
    contains `Environment dashboard update failed`, after firing the retry
    timer(s) the last publish is `WORKING` (or `NEEDS YOU` when a pending
    permission `held` exists at retry time), and the recorded retry delays are
    `[1000, 2000]` for the double history failure and `[1000]` otherwise.
21. Given a successful start, when a publish fails while handling a
    `user.message` (delivery idle) at 200, and a permission request arrives
    while tracking has failed, then after the retry the publishes are
    `WORKING`, `UNKNOWN`, `NEEDS YOU`, and after the permission completes
    `WORKING` with since `200`; history was read exactly twice.
22. Given a successful start, when the parent idles at 200 and the following
    reconcile's activity call fails, then publishes are `WORKING`, `YOUR TURN`,
    `UNKNOWN`, and after the retry `YOUR TURN` (tracking does not stay stuck).
23. Given a reconcile whose activity answer is delayed, when a new
    `user.message` (delivery idle) at 300 arrives before the answer
    (`hasActiveWork: false`), then the last publish is `WORKING` since `300` and
    no retry was scheduled.
24. Given `joinSession` rejects, then the only publish is `UNKNOWN`, importing
    the extension fails with the same error message, and no retry is scheduled.
25. Given a startup snapshot with an attached running shell and processing
    false (with activity either true or false), then the first publish is
    `WATCHING` since `100`; when tasks empty, activity goes false and
    `session.background_tasks_changed` arrives, then `YOUR TURN` with a
    non-empty since; the task list was queried twice.
26. Given a startup snapshot with an attached shell while processing is true,
    then `WORKING`; parent `assistant.idle` gives `WATCHING`; a steering
    `user.message` at 300 gives `WORKING` since `100`.
27. Given a startup snapshot with only a detached running shell, then the last
    publish is `WORKING`.
28. Given a watching chat whose post-idle task query fails once, then
    publishes are `WATCHING`, `UNKNOWN`, `WATCHING` since `100`.
29. Given a startup snapshot with a running background agent and processing
    false, then `SUBAGENTS` since `100`; when the agent becomes idle, activity
    goes false and tasks change, then `YOUR TURN`.
30. Given an active run, when a background child starts (101), the parent
    idles (102), an attached shell appears and disappears (103, 104), the child
    completes (105) and the parent's `session.idle` arrives (106), then the
    publishes are exactly `WORKING` since 100, `SUBAGENTS` since 100,
    `YOUR TURN` since 105 took 5.
31. Given a startup snapshot with a running background agent while processing
    is true, or with only a running shell task without attachment, then the
    last publish is `WORKING`.
32. Given a startup `SUBAGENTS` state whose post-idle task query fails once,
    then publishes are `SUBAGENTS`, `UNKNOWN`, `SUBAGENTS` since `100`.
33. Given an active run, when a `task` tool starts (101), a sync child starts
    (102), the child completes (103), the tool completes (104) and the parent
    idles (105), then publishes are exactly `WORKING` 100, `SUBAGENTS` 100,
    `WORKING` 100, `YOUR TURN` since 105 took 5.
34. Given a successful synchronisation (after two history failures), then the
    session folder `/sessions/abc` is published exactly once and the metadata
    snapshot was requested once.
35. Given a remote session, then the folder option is unset (recorded `null`).
36. Given the metadata snapshot fails, then no folder is published, the last
    state publish is still `WORKING`, no retry is scheduled, stderr contains
    `could not publish the session folder` and does not contain
    `Environment dashboard update failed`.
37. Given an active run, when the parent idles at 352, then a new
    `user.message` (delivery idle) at 400 and idle at 405 arrive, then no tools
    were registered and the publishes are exactly `WORKING` 100,
    `YOUR TURN` 352 took 252, `WORKING` 400, `YOUR TURN` 405 took 5.

### 11.4 Installer

38. Given an empty temporary home and prerequisites stubbed out, when the
    installer runs without `--apply`, then the home is still empty.
39. Given an empty home, when installing, then each of the five files equals
    its source byte-for-byte with its declared mode; a second plan has no
    writes and no creates; `~/.tmux.conf`, `~/.tmux/ai-agents-shortcuts.conf`,
    Ghostty config and `~/.copilot/settings.json` do not exist; uninstalling
    leaves the home empty.
40. Given an installation whose receipt no longer lists `md-view` and a foreign
    file at `.local/bin/md-view`, when planning an install, then it fails
    mentioning `unowned`; uninstall removes owned files (the launcher) but
    keeps the foreign file. Given instead that the receipt lacks `md-view` and
    the file is absent, then installing writes `md-view` from source and the
    receipt lists it again.
41. Given a pre-existing `~/.tmux/ai-agents.conf`, when planning, then it fails
    mentioning `unowned`, the file is unchanged and `.local` was not created.
42. Given an installed `ai-agents.conf` edited by the user, when planning
    either install or uninstall, then it fails mentioning `modified`; the edit
    and the receipt remain.
43. Given a pre-existing `~/.copilot/settings.json`, when installing and then
    uninstalling after the user put a file inside `left_pinky`, then that file
    and the settings file are intact.
44. Given `~/.tmux` is a symlink to an outside directory, when planning, then it
    fails mentioning `symlink` and the outside directory stays empty.
45. Given the second atomic write of a fresh install fails, then the error
    propagates and the home is empty afterwards.
46. Given an installed launcher was deleted, when installing again, then it is
    restored.
47. Given no receipt and a pre-existing `ai-agents.conf`, when planning and
    executing an uninstall, then the plan removes nothing and the file is intact.
48. Given prerequisites stubbed, when the command line runs with `--apply`, then
    it returns 0 and the receipt exists; with `--uninstall --apply` it returns 0
    and the home is empty.
49. Given an installation where `right_pinky` was replaced by a symlink, when
    planning an uninstall, then it fails mentioning `symlink` and the launcher
    still exists.
50. Given an installation and a plan rewriting the launcher and the receipt,
    when the receipt write fails, then the launcher and receipt bytes equal
    their pre-update contents.

### 11.5 Launcher and dashboard (isolated tmux)

51. Given a new session, then windows 1–10 carry the expected names in order;
    when window 7 is selected and the launcher runs again, then window list
    (indices, names, window ids, pane ids, pane PIDs) is unchanged, window 7 is
    still selected, and session option `status` is `5`.
52. Given window 7 was killed, when the launcher runs, then there are ten
    windows and all others are byte-identical in that listing.
53. Given global `renumber-windows on` and `mouse off`, and the configuration
    installed by the installer, when ensuring, killing window 7 and ensuring
    again, then ten windows exist, the others are unchanged, session `mouse` is
    `on`, global `mouse` is still `off`, global `renumber-windows` still `on`,
    and `~/.tmux.conf` was not created.
54. Given an existing session `ai-agents` without the marker, when ensuring,
    then it fails mentioning `unmanaged` and its windows are unchanged.
55. Given window 3 renamed to `Other work`, when ensuring, then it fails with
    `Unexpected window` and nothing changes.
56. Given the session was killed, when ensuring, then ten windows exist sharing
    no listing line with before, and the session state renders `READY`.
57. Given a Copilot-simulated pane with since = now − 83, then the timer for
    `WORKING`, `SUBAGENTS` and `WATCHING` matches `1m23s`–`1m29s`, the cell
    contains it and `#[range=window|1]`, `WATCHING` cells contain
    `#[fg=colour117]` and `SUBAGENTS` cells `#[fg=colour141]`. For `YOUR TURN`
    with since 1000000000 and took 252 the timer is `4m12s @HH:MM` (local time
    of that instant) and the cell contains `#[fg=colour226]YOUR TURN  4m12s @HH:MM `;
    without took it is `@HH:MM`. With since = now − 83 and a waiting reason the
    timer matches `1m2[3-9]s ago` and the cell contains `#[fg=colour244]WAITING`.
    For `NEEDS YOU`, `ERROR`, `READY`, and `YOUR TURN` with since unset, the timer
    is empty. `status-interval` is `1`.
58. Given a Copilot-simulated pane, when its pane title is the bare default
    `GitHub Copilot`, the rendered title is empty; a named chat ending in
    ` - GitHub Copilot` shows only the name; a name that itself begins with
    `GitHub Copilot` keeps that prefix while losing the suffix; and a title in
    which `GitHub Copilot` is followed by more letters is shown unchanged.
59. Given the shortcut fragment and an attached client, when sending Cmd+1 …
    Cmd+9, Cmd+0, then windows 1 … 10 are selected in turn; Cmd+Shift+] from
    10 wraps to 1; Cmd+Shift+[ from 1 wraps to 10; Cmd+7 then Cmd+; returns to
    10; an existing root binding for Alt+1 still fires; while the client is on
    the `unrelated` session Cmd+1 does not change its window; after setting
    `@ai-agents-managed` to `0`, Cmd+1 does nothing and the attention jump
    fails mentioning `unmanaged`.
60. Given windows 2, 4, 6 `YOUR TURN`, windows 3 and 8 `NEEDS YOU`, and a
    waiting reason on 4 (state `WAITING`), starting on window 1, Cmd+`
    selects 3, 8, 3; from 1, two rapid presses end on 8; after 3 and 8 become
    `WORKING`, presses select 2 then 6; after 2 becomes `WORKING`, a press shows
    `No other chats need attention` and window 6 stays selected.
61. Given windows 2, 3, 5, 7 publishing `YOUR TURN`, `REVIEW`, `DECIDE`,
    `BLOCKED`, then each renders state `YOUR TURN` and successive attention
    jumps from window 1 visit 2, 3, 5, 7, 2.
62. Given a Copilot-simulated pane titled `Ship it - GitHub Copilot` with a
    retired `@env-copilot-reason`, the title is `Ship it`; with reason
    `review #[fg=red]` the title is `Waiting on: review # [fg=red] | Ship it`, also
    when the state is `REVIEW`; after unsetting the reason it is `Ship it`.
63. Given a plain-shell pane with a stale `YOUR TURN` option, then it renders
    `READY` and the attention jump leaves window 1 selected.
64. Given an extra window 11 with `NEEDS YOU`, then the attention jump ignores
    it and window 1 stays selected.
65. Given an installed workbench, the fake `code`, window 3 pointing at a
    session folder containing `plan.md` (mtime 100), `files/summary.md` (300),
    `checkpoints/index.md` (200) and `rewind-file-snapshots/README.md` (400),
    window 4 with no folder and window 5 with an empty folder: Cmd+Shift+M on
    window 4 shows `No Copilot session folder for this chat`, on window 5
    `No Markdown in this chat's session folder yet`, and `code` has not run;
    on window 3 `code` receives exactly `--user-data-dir <profile>`,
    `--extensions-dir <profile>/extensions`, `--reuse-window` and the resolved
    `files/summary.md` path, with `VSCODE_IPC_HOOK_CLI` empty; the profile's
    settings map `*.md` to `vscode.markdown.preview.editor`. Calling the
    Markdown action for a pane of `unrelated` fails with
    `not in the ai-agents session`.
66. Given window 1 then 3 selected and an attached 240-column client, when the
    hotkeys button (terminal row 1, i.e. `status-format[0]`, column 238) is clicked, then the output shows
    `Digits shortcuts` and `Cmd+Shift+M`; a second click closes the menu and
    Up+Enter leaves window 3 selected; clicking again then Up+Enter runs
    "Last window" (window 1); clicking terminal row 2 column 10 selects window 2.
67. Given window 6 is `YOUR TURN` with owner `fixture` and window 7 selected,
    when right-clicking terminal row 1 column 125 (window 6's cell) and entering
    `review, "quoted"; #{pane_id} #[fg=red] $(not-a-command)`, then window 6's
    reason equals that text exactly, its state is `WAITING`, its title contains
    `Waiting on:` and `# [fg=red]`, the window list is unchanged and window 6 is
    selected. Reopening and submitting unchanged keeps the exact text;
    re-sourcing the configuration keeps it; publishing `WORKING` clears it; and
    returning to `YOUR TURN` renders `YOUR TURN`.
68. Given window 1 idle, right-click entry `external review` saves it; a second
    prompt where the text is changed and Escape pressed keeps `external review`;
    a third prompt submitted empty clears it and the state is `YOUR TURN`; a
    fourth prompt submitted after the state switched to `WORKING` saves nothing.
69. For each of `NEEDS YOU`, `ERROR`, `WORKING`, `SUBAGENTS`, `UNKNOWN` written
    to `@env-copilot-state`, and for a changed `@env-dashboard-owner`, on window
    6 (with windows 1 and 6 both holding reason `review` owned by `old`): window
    6's reason is cleared and window 1's is kept. Switching window 6 from
    `YOUR TURN` to `DECIDE` keeps its reason.
70. Given `@hand-status-now` fixed at 200000, the duration for elapsed −5, 0,
    59, 60, 3599, 3600, 86399, 86400, 90000 seconds is `0s`, `0s`, `59s`,
    `1m0s`, `59m59s`, `1h0m`, `23h59m`, `1d0h`, `1d1h`.

### 11.6 Markdown viewer

71. Given a temporary home with a fake `code` on `PATH`, when `md-view` is run
    on a missing file, then it exits 1, stderr contains `Not a file`, and
    `code` did not run. Given then a user-edited profile settings file and an
    existing `doc.md`, when `md-view doc.md` runs, then `code` runs and the
    settings file is unchanged.

### 11.7 Additional edge cases (not covered by the reference tests)

72. Given `--next-attention` together with `--no-attach`, then the launcher
    exits 2 with a usage error.
73. Given a missing environment directory (or one that is a symlink) for a
    window that must be created, then ensure fails with
    `Missing independent environment:` before any window is created; when the
    window already exists, the directory is not checked.
74. Given windows are missing and neither fish nor a usable login shell is
    available, then ensure fails stating a login shell is required and creates
    nothing; given no windows are missing, no shell is required.
75. Given `~/.tmux/ai-agents.conf` is absent, then the launcher fails with
    `Missing session configuration:` and exit 1.
76. Given `--no-attach`, then stdout is exactly `Ready: ai-agents` and the
    process exits 0 without attaching.
77. Given two launchers start concurrently on a server without the session,
    then exactly one session with ten windows results (the lock serialises).
78. Given `md-view` cannot find `code` on `PATH` or in either application
    location, then it exits 1 with a `md-view:` message and no profile is
    required to exist afterwards beyond what was created; given `md-view` is
    run with `VSCODE_*` and `ELECTRON_RUN_AS_NODE` set, then `code` sees none
    of them.
79. Given `md-view` runs with no settings file, then `User/settings.json` is
    created once with exactly the keys of 4.2 and later runs leave it unchanged.
80. Given a receipt with `version` 2, an unknown file key, a directory outside
    the managed set, a non-hex hash, or mode 0600 or `true`, then every plan
    fails before any change.
81. Given an uninstall where a created directory holds an unrelated file, then
    the run prints `KEEP non-empty directory <path>` and succeeds.
82. Given another installer holds the home lock, then `--apply` fails at once
    with exit 1.
83. Given a non-macOS platform or a missing prerequisite, then install preview
    and apply fail with exit 1 listing the missing commands; `--uninstall` still
    works.
84. Given the extension runs without `TMUX` or with a malformed `TMUX_PANE`,
    then it joins the session, never invokes tmux and ignores events.
85. Given repeated synchronisation failures, then retry delays double to and
    stay at 30000 ms and reset to 1000 ms after a success.
86. Given the Copilot process exits while another process's PID is in
    `@env-dashboard-owner`, then the exit handler leaves the pane options
    alone; when the PID matches, all five extension options are unset.
87. Given a Copilot pane with no published state, then it renders `COPILOT` in
    `colour244` with an empty timer; given a dead pane, `ERROR`; given a
    non-shell foreground program in a pane, `WORKING`.
88. Given `md-view` fails for the Markdown shortcut, then the last stderr line
    (or `md-view failed`) is shown as a tmux message and the launcher exits 0.
89. Given fish is absent, then the environment shell is the login shell when
    it is an absolute path to an executable file, and absent for a relative
    name or a missing file; new windows start in that shell. Given fish is
    present, it wins over the login shell.
