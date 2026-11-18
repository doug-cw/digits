# Context and harness maintenance

Use when recording a shared workflow lesson, editing or installing Digits, or changing instructions, plugins, or how chats refresh.
Scope: only the user's shared harness; it does not coordinate other chats automatically and deploys nothing.
Sources: `https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions`, `https://code.claude.com/docs/en/memory`, `https://code.claude.com/docs/en/plugins/create`, `https://code.claude.com/docs/en/commands`, current CLI help, and the plugin guide in the Digits repository.
Reviewed: 2026-11-16.
Recheck: the source version against the installed version, what the CLI supports today, and which sources a chat really loaded.

## Four different artifacts

Decide which artifact you are touching before you change anything:

1. The Digits source repository: reviewed, and the single place where edits happen; an installed cache is never edited.
2. The installed, versioned context: immutable, and unaffected by whatever branch happens to be checked out. A plugin loaded straight from a checkout (through `DIGITS_PLUGIN_DIR` or `--plugin-dir`) is different: it follows that checkout's branch and files.
3. This machine's private bindings: where non-secret local facts authoritatively live, every one carrying provenance; they are never exported.
4. Whatever a running chat has already loaded: this can lag behind until the chat is refreshed through a supported path such as a new session or a resume.

- `context/bootstrap.md` is the only maintained source of automatic context. The context installer renders it with local paths and stamps it with a content fingerprint; nobody maintains a hand-written copy of the generated file.
- Context installation is unrelated to the dashboard installer and to activating the plugin. It leaves alone settings, MCP sign-in, terminal configuration, repositories, schedules, and every other chat.

## Explicit shared-memory updates: source first

Use this when the user says "remember this" or "put this in Digits". Jotting the lesson into local memory does not change the maintained repository, so it does not count.

1. Distill a durable, non-sensitive workflow lesson from the evidence you were given; keep no transcript and credit no third party. If the scope is fuzzy, ask; check what current guidance already says before you add or replace anything. Personal or sensitive data is never stored as memory. Machine facts that are not secret belong in bindings, while task progress and receipts belong in session artifacts.
2. Find the Digits source checkout that has been verified for this environment, then look at its remote origin, current branch, and any edits (staged or not). Do not disturb unrelated in-progress work or the plugin path currently in use: never switch, stash or reset the branch of a checkout that a live plugin loads from. Do that work in a separate full clone and say which one. Where an installed configuration file is generated from a repository, change its source, not the installed copy. Make the change in the smallest existing topic under `context/` that fits; add a bootstrap route only when nothing else will do. Generated instructions and installed releases stay untouched. Installed context and plugins reach every chat this user has open, so install solely from reconciled source you plan to publish, never from a branch that lives unpushed in some other clone, and flag any other clone or branch carrying Digits edits that are not yet published. Uncommitted Digits work belonging to a different chat must not end up in your commit or merge unless that is explicitly approved.
3. If the change alters behavior: write a de-identified routing case, raise the context version, read through the diff, and then run the context-focused tests alongside the repository's source and secret guards. The user's Git index is off limits; to check a source snapshot without staging their work, use a disposable index.
4. Use the existing installer, with its ownership guards, to preview and then apply; preview a second time and make sure the installed copy agrees with the source. A request to save one lesson authorizes only that narrow source edit and install, not any unrelated policy change. In your report keep four items apart: where the source lives, what the install did, whether a commit or push took place, and the warning that chats already open may hold stale context. Never claim a commit or publication that did not happen; pushing or opening a PR still waits for the user to ask.

Run these at the root of the source repository:

```sh
python3 -m unittest discover -s tests -p 'test_context.py'
python3 context_install.py
python3 context_install.py --apply
python3 context_install.py
```

The final preview must report that nothing needs changing (the installer prints `No file changes needed.`). Further checks follow the repository README.

- An optional mirror in host memory must respect its own privacy and scope rules and never replaces reviewed source.
- One explicit lesson never justifies a retrospective across chats or moving that workflow's cursor; keep `/digits:self-improve` for when the broader review is actually requested.

## Install/update/rollback

- Start every change with a preview: in the repository root, run `python3 context_install.py`.
- An entry file that already exists but is not owned by the installer has to be reviewed first; carry anything worth keeping over to source or bindings, then rerun with `--adopt-sha256` followed by the precise hash the preview printed.
- Local edits to any owned file stop an update and a rollback alike.
- `--apply` installs. `--rollback` previews restoring the most recent snapshot, and `--rollback --apply` performs it.
- Receipts and backups are private and stored outside every instruction-discovery path.
- A rollback restores the previous entry and receipt but keeps the immutable topic versions that running chats may still link to; a private catalog of retained versions keeps them owned.
- Installing again over a restored hand-written entry requires hash-bound adoption once more.
- Do not prune snapshots while anything might still reference them.
- Ownership checks are never bypassed, directories are never removed in bulk, and binding contents never get copied into source.
- Once changes have been reviewed, raise the version. Ahead of publishing, the applicable tests and the source and secret guards must pass. Only a user request leads to a push or PR.

## Loaded-state canary

What is loaded:

- For what a newly started process would pick up, check today's CLI help and `copilot instruction list --json`. Within an open chat, `/instructions` and `/env` show the sources that particular session is using.
- Command-line discovery reveals nothing about whether an already-running chat picked up changes.

Refreshing chats:

- With the plugin's `digits-refresh` extension, a chat that becomes idle (nothing awaiting approval, no subagent active, no turn in flight) reloads updated user instructions, skills, and extensions without restarting. Its following turn uses them, and a note appears in the chat to say so. The extension does not restart or interrupt anything, and it leaves MCP connections as they are.
- Fall back to native `/restart` when a chat predates the extension, when the extension warned that its refresh was incomplete, or when MCP configuration, settings, or plugin registration changed; then verify which sources are loaded. Opening a fresh session, or quitting and resuming, is equally fine.
- Busy chats are never restarted, and nobody answers their pending approvals for them. Given a request to "refresh all chats", report every chat's state (idle or busy) and explain the native `/restart` option, but send no commands into the busy ones.
- Claude Code, per its current documentation: instruction files, including files they import, load at launch, so edits to them reliably reach a chat only in a new session; `/context all` shows what loaded. After editing a plugin loaded with `--plugin-dir`, run `/reload-plugins`; `/reload-skills` rescans skill and command directories. Observed but undocumented, so recheck after upgrades: `/reload-skills` also picked up new `--plugin-dir` skills, and `/clear` starts a new session id.
- `/skills reload` updates the list of skills only; it does not reload the automatic instructions. If a fresh `copilot skill list --json` lists a command this chat cannot see, the likely cause is an outdated catalog rather than a failed install, and repeated activation attempts are not an authentication issue. Registering plugins and reloading extensions each follow a procedure of their own.

Naming:

- Plugin commands carry the `digits:` prefix exactly once.
- Under `plugin/skills/`, neither the folder nor the skill name gets a prefix (for example `inter-env`); personal skills kept outside the plugin are allowed to start with `digits-`.
- Find helpers via the loaded skill's real directory, never a guessed checkout.

Behavioral evaluation:

- Use throwaway homes and workspaces, de-identified fixtures, and read-only tools, with MCP servers, writes, shell, and outbound sends disabled. Never use production queries, approvals, real chat or GitHub writes, or task state carried over from elsewhere.
- Cover every model family you rely on, using multiple cases, repeated runs, and variants kept back from development.
- Score what the model really opened and what really resulted, ignoring the path it reports having taken.
- If a credential or model-authentication request is denied, the evaluation ends; do not switch credentials.
- Irrelevant-task controls: only the bootstrap loads automatically, and a small unrelated question must not open the data, issue-tracker, or infrastructure pages.
- In addition, verify rollback, rendered size, the absence of duplicate registration, and that no link is broken.
- Keyword-based static tests act as guards; passing them demonstrates neither that the model follows the rules nor that it is safe.

## Maintainer rule

- When the user explicitly asks for an incremental retrospective, use `/digits:self-improve`. It goes over chats since its previous successful run, overlapping slightly so late-arriving history is not missed, and offers a readable proposal for approval. Its private cursor moves forward only once the approved edits (or an approved choice to make none) are in, checks pass, and the installed source has been verified.
- Incomplete, failed, rejected, or cancelled runs keep the previous boundary. The retrospective never runs by itself during normal work, and its live cursor is not kept in this library.
- Keep source edits narrow. Build on the helpers, generators, and naming already present, repair bugs that are bound up with the change, and leave out unrelated tidying as well as prompts tailored to individual models.
- Grow the corpus from recurring lessons through small cases and review, not by letting agents rewrite it freely. Fold a lesson into the mechanism that already exists instead of piling up global rules.
- Invariants that can be checked deterministically belong in an existing test or source/secret guard, not in prose. Matching a keyword is not evidence of safe behavior, and no hook gets added whose only job is to repeat a judgment call.
- Treat harnesses built by others as something to learn from: take over durable mechanisms with pinned provenance, but turn down anything tied to a personal identity, any hidden helper it depends on, any assumption about live services, and any permission at odds with this harness.

See the authoring contract in the [context README](../README.md) and session-state handling in [continuity](continuity.md).
