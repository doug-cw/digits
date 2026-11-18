---
name: restart-chats
description: Restart the idle Claude Code chats in the ten ai-agents windows so they pick up a changed shell profile, DIGITS_PLUGIN_DIR or plugin files. Use when the user says "restart the chats", "restart all of them", "reload the environments" or "/digits:restart-chats [environment...]".
user-invocable: true
---

# Restart chats

Usage: `/digits:restart-chats [environment...]` (for example `left-ring right-pinky`; no names means all ten)

A chat started before a profile change (a new `DIGITS_PLUGIN_DIR`, for example)
keeps its old environment until it is restarted. This skill hands the work to
the launcher, which restarts each chat in its own window, one at a time.

## Run it

Run one command and show its output to the user unchanged:

```
ai-agents --restart [environment...]
```

Pass on the environment names the user gave (`left-ring`, `left_ring` and
`Left Ring` all work). Run it once; do not loop or retry it.

For each chosen window the launcher, in order:

1. leaves the chat alone, with a reason, unless it is a Claude Code chat whose
   dashboard state is `READY` or `YOUR TURN`, with an empty composer and no
   `esc to interrupt` footer. It also skips plain shells, Copilot CLI chats,
   the chat running the command (this one) and any chat while memory is under
   30% free or the one-minute load is at or above the core count;
2. sends `/exit`, waits for the shell, and replaces it with a fresh login shell;
3. types `digits-claude --continue` when Claude Code has a saved conversation
   for that folder, otherwise `digits-claude`, and checks that the chat stays up.

## After it runs

- Summarise in one or two lines: which chats restarted, which were skipped and
  why. Quote failure lines exactly.
- This chat is never restarted by its own command. If it needs a restart too,
  tell the user to type `/exit`, then `exec $SHELL -l` and
  `digits-claude --continue`.
- A skipped chat stays as it was. Suggest the user finish or clear its draft,
  or wait for it to go idle, and then run the command again for that
  environment. Never type into a chat to clear it.
- If `ai-agents` is not found, say so and point at the Digits installer; do not
  send keys to the panes yourself.
