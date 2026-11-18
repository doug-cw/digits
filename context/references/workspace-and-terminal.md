# Workspace, shell, and terminal links

Use when picking the checkout to work in, fixing local links that misbehave, or changing terminal settings.
Scope: the ten separate environment roots plus the user's approved local terminal setup.
Sources: local configuration, the dashboard README, and the terminal fragments that ship with the source repository.
Reviewed: 2026-11-16.
Recheck: the current path and status, whether the repository is actually present, the settings currently loaded, and how the terminal really behaves.

Decision procedure:

1. Identify which of the ten roots this environment is and confirm the exact checkout before editing.
2. Compute per-clone values from that checkout, in the shell named by the private tool binding.
3. Present clickable things as absolute `file:///` links; inspect live terminal configuration before changing it.

## Environment identity

- There are ten roots: `{{HOME}}/left_{thumb,pointer,middle,ring,pinky}` and `{{HOME}}/right_{thumb,pointer,middle,ring,pinky}`, unless the launcher was given another parent directory with `AI_AGENTS_ROOT` or `--root`. Each root is one tmux window in the dashboard.
- Clones inside the roots are full, independent clones. Never convert them into worktrees, and never assume branch or dirty state is shared between roots.
- Roots share a list of repositories, not edits. A recently added repository may be missing from some roots. Confirm this environment's exact checkout before editing.
- Any other clone location (such as an older `{{HOME}}/code` directory) is separate: neither an alias nor a fallback. Record such legacy roots in the private tool binding, and never quietly migrate, delete, or sync them.
- Same-named repositories from two organizations are cloned as `organization--repository`.
- Shared across all environments, not copied per root: user settings, instructions, integrations, and durable skills. Independent in each environment: ticket context, sessions, and live task state.
- Helpers are found where the loaded plugin skill lives; a legacy personal-skills folder, or a path guessed from a different environment, is the wrong place to look.
- If a local inventory or drift-check helper exists, it and its manifest path are recorded in bindings. They are lookup aids, never authority to sync repositories.

## Shell and per-clone environment

- Commands for the user target the shell named in the private tool binding, or POSIX `sh` if none is named.
- Use shell-specific assignment or activation syntax only when it matches that shell; fish, for example, sets variables with `set -x`, not `export VAR=...`.
- Non-interactive agent commands derive per-clone values — such as the isolated dev schema described in [local profile and isolation](../domains/data-warehouse.md#local-profile-and-isolation) — from the selected clone, never from whatever another tab happened to export.

## Local links and clicks

- Clickable items must be explicit absolute `file:///` links, percent-encoding spaces and other reserved characters. Terminals frequently fail on a plain path, or on a Markdown link whose target simply begins with `/`. Commands keep ordinary absolute paths.
- tmux mouse support is on in the dashboard and stays on; disabling it globally is not an acceptable way to fix hyperlinks.
- With the optional Ghostty fragments, open local links with Shift+Cmd-click, because tmux may capture a plain Cmd-click.
- The tmux fragment enables `allow-passthrough` so Copilot CLI image previews reach the terminal; without it tmux silently drops image data. If images still do not appear after enabling it, restart that pane's chat with `copilot --resume`. Images render only while the pane is visible.
- Terminals other than Ghostty need their own equivalent settings. Inspect the live configuration before changing it instead of replaying a fix from an old conversation.

## Dashboard and Markdown viewer

- The "hotkeys" button at the top right of the dashboard lists every shortcut and runs the one you pick.
- Once the optional fragments are in place:
  - Cmd+1…Cmd+9 and Cmd+0 select windows 1 through 10.
  - Cmd+Shift+[ steps back one window; Cmd+Shift+] steps forward one.
  - Cmd+; returns to the last-used window.
  - Cmd+` moves to the next chat needing attention: NEEDS YOU first, then YOUR TURN, never WAITING.
  - Cmd+Shift+M opens the current chat's newest session Markdown (from its files, plan, research, or checkpoints) in the viewer; it relies on the dashboard extension which exposes the session directory for every pane.
- The fragments are opt-in, and they take over the terminal's built-in tab and window shortcuts. After changing key bindings, reload the terminal configuration; restarting a Copilot chat does not apply them.
- `md-view '/abs/path.md'` opens Markdown in a dedicated VS Code instance with its own preview-rendering profile. The first call opens one window; later files open as tabs there. Regular editor windows are never reused.
- Status labels such as YOUR TURN or WAITING are only observed hints; they grant no authority and are no evidence that a scheduled job executed.
- A settled chat shows YOUR TURN along with how long its last turn took and the local time it finished; chats are not required to report status.
- Before changing another pane or session, consult [continuity](../workflows/continuity.md) and the `inter-env` helper.
