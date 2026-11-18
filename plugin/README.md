# Digits plugin

This directory is the Copilot-facing part of Digits, packaged in the Agent
Plugins 1.0 format. It ships complete workflows with guards built in: each skill
reads first, shows you what it would do, and waits for approval before anything
leaves your machine.

| Command | What it bundles |
|---|---|
| `/digits:standup-update` | Drafts your daily update from earlier updates, recent chats, the issue tracker and live GitHub, in a configurable format; optional headless helpers and a scheduled runner |
| `/digits:request-review` | Composes a short review request for one or more PRs and, after approval, posts it to your review channel mentioning the requested reviewers; optional mark-ready and ticket transition |
| `/digits:review-reactions` | Dry run, then approved status reactions on your own review-request posts |
| `/digits:draft-pr-sweep` | Read-only bucketing of your draft PRs with next actions offered in one approval form that hands off to other skills |
| `/digits:assess-and-address` | Assesses PR review feedback, fixes valid items, resolves automated threads and drafts replies to humans |
| `/digits:rebase-pr` | Isolated, intent-preserving rebase pushed with a lease pinned to the old head |
| `/digits:update-shared-workflows` | Semver-aware inventory and dry-run-first bumps of shared workflow and action references |
| `/digits:investigate` | Read-only, evidence-first investigation that ends in options and a recommendation |
| `/digits:challenge-pass` | Adversarial, read-only check of conclusions by a separate agent |
| `/digits:inter-env` | Finds chats across the ten environments, shows progress, and delivers individually approved messages and guarded skill reloads through tmux |
| `/digits:self-improve` | Incremental review of recent work chats, proposal-first context improvements, and a private success checkpoint |
| `/digits:done` | User-only: recaps the chat, marks it `[DONE]` and opens a fresh session |
| `/digits:summarize` | Read-only four-part recap of the current chat (goals, progress, blocking questions, next steps), also saved in the session workspace |

This is a personal workflow package, not organization policy. No organization
defaults (channels, sites, repositories, people) are built in; you supply them
through your private bindings.

## Install and verify

Use a local clone path or a Git repository as the marketplace source, then run
these four commands in order:

```bash
copilot plugin marketplace add <path-or-repo>
copilot plugin install digits@digits
copilot plugin list --json
copilot skill list --json
```

The plugin list should show `digits` exactly once, enabled. The skill list should
show each of these thirteen names exactly once with source `plugin`:
`standup-update`, `request-review`, `review-reactions`, `draft-pr-sweep`,
`assess-and-address`, `rebase-pr`, `update-shared-workflows`, `investigate`,
`challenge-pass`, `inter-env`, `self-improve`, `done`, `summarize`.

The plugin name supplies the `digits:` command namespace. Install it once at user
scope, not once per environment. Built-in and third-party skills are left alone.
To try it without touching your real setup, point `COPILOT_HOME` at a temporary
directory first.

What the package does not contain: MCP server registrations, hooks, the
dashboard extension, shared settings, permission or trust records, or any
terminal installer. Installing it never launches agents, schedules jobs, runs
helpers, stores credentials or logs in anywhere. Integrations (the GitHub CLI, a
chat MCP server, an issue-tracker MCP server) are configured separately.

## Configuration

Every organization-specific value is resolved in this order, stopping at the
first source that has it:

1. explicit arguments to the slash command;
2. your private bindings file `~/.config/digits/context/tool-and-repo-bindings.md`
   (plain `- key: value` lines, usually under a `## Digits plugin` heading; never
   secrets);
3. one batched ask covering every value that is still missing: a single call to
   the host's question tool (`ask_user` in Copilot CLI, `AskUserQuestion` in
   Claude Code), or one numbered list answered in a single reply when the
   questions do not fit one call.

Identifiers (channel, user, group, project, field, cloud or site IDs) are never
guessed or hardcoded; skills look them up with live tool discovery each run.

Example bindings (fictional):

```markdown
## Digits plugin
- review_channel: #example-org-reviews
- review_default_groups: example-org-platform
- issue_tracker_site: example-org.atlassian.net
- standup_format: four-field
- standup_timezone: Europe/Berlin
- shared_workflow_repos: example-org/shared-workflows
```

| Key | Default when not bound | Read by |
|---|---|---|
| `review_channel` | ask | request-review, review-reactions |
| `review_request_phrase` | `review request for` | request-review |
| `review_hide_unfurls` | `true` | request-review |
| `review_issue_transition` | transition skipped | request-review |
| `review_default_groups` | no group suggestion | request-review |
| `automated_review_size_limit` | no size check | request-review, draft-pr-sweep |
| `review_reaction_feedback` | `speech_balloon,comment` | review-reactions |
| `review_reaction_approved` | `white_check_mark` | review-reactions |
| `review_reaction_merged` | `twisted_rightwards_arrows,merge,merged` | review-reactions |
| `issue_tracker_site` | ask, or produce a GitHub-only draft | standup-update |
| `standup_format` | `yesterday-today-blockers` (or `four-field`, or custom labels) | standup-update |
| `standup_output_dir` | `~/.local/state/digits/standup` | standup-update |
| `standup_timezone` | the machine's local zone | standup-update |
| `standup_field_limit` | about 1,200 characters for the progress field | standup-update |
| `standup_ticket_links` | `bare` (or `plain`) | standup-update |
| `standup_priority_query` | no ranking | standup-update, draft-pr-sweep |
| `shared_workflow_repos` | ask | update-shared-workflows |

Reaction keys hold comma-separated emoji names: the skill adds the first one, and
any later name is an equivalent that, if already present, means no reaction is
needed. The headless shell helpers do not read the bindings file; they use
environment variables (see below).

## Finishing a chat

`/digits:done` asks the model for a final recap: 2 to 4 bullets, at most 120
words, covering what was accomplished, what was validated, and any material
unfinished item, drawn only from the conversation. After that reply and the
chat's natural stop, the `session-done` extension prefixes the session title
with a single `[DONE]`, reads the title back to verify it, and then queues the
native `/new`. The old chat keeps its recap and marker across exits and reboots;
the new chat starts with fresh context in the same directory. Nothing is
committed, deleted or changed anywhere else.

It is a user-only skill rather than an extension slash command because Copilot
CLI 1.0.109 prints a spurious `No client found for command` error for extension
slash commands (upstream issue github/copilot-cli#5412). The marker and reset
need experimental extensions enabled (verified on 1.0.109); without them only
the recap happens.

Details:

- Refused, with one error note: arguments after the command, remote sessions,
  and sessions without a saved local workspace.
- Title normalization: runs of control characters become one space, double
  quotes become single quotes, surrounding whitespace is trimmed, and an empty or
  missing title becomes `Untitled session`. A title that already starts with
  `[DONE]` is kept as is.
- Titles stay within 100 characters: at most 93 characters are kept after the
  `[DONE] ` prefix, without splitting an emoji or other surrogate pair.
- If the rename fails or cannot be verified, `/new` is not queued. If the reset
  is not accepted, the marker stays and you run `/new` yourself.

## Automatic refresh

The `digits-refresh` extension watches three groups of files: your
`copilot-instructions.md` plus user-level instruction sources; the plugin's
`plugin.json` and every `SKILL.md` in the plugin and in your personal skills
directory; and the extension code files (`.mjs`, `.cjs`, `.js`, excluding tests)
of the plugin and of your personal extensions directory. A change must stay
stable for three seconds. Once the chat is idle (not processing, no active work,
no pending permission requests, no running subagents) it writes a short note
into the chat and reloads instructions, then skills, then extensions, in place,
so the next turn sees the new content. No keystrokes are sent to tmux, the
conversation survives, and MCP connections stay as they were. If a reload fails,
the chat shows one warning recommending `/restart` once it is idle; there is no
retry loop. Remote sessions are skipped.

A chat that was already running when the extension first shipped needs one
`/restart` while idle to load it. Changes to MCP servers, settings or plugin
registration follow their own procedures. A plugin installed from a separate
terminal is not visible to the registry of an already running chat: run
`/plugin install digits@digits` in that chat while it is idle (or restart it
when idle), and `/skills info inter-env` should then resolve to this plugin.

Do not break into a working chat, do not answer a prompt that belongs to a
different chat, and do not script restarts.

## Maintaining and updating

Edit the source repository (`plugin/skills/`,
`plugin/com.github.copilot/extensions/`), never an installed cache. Run the
repository checks and helper tests, review the change, and bump `plugin.json` and
the marketplace entry together.

A local-directory marketplace loads straight from source, so keep that path
available and on a revision that contains the plugin. A Git-backed marketplace
needs `copilot plugin marketplace update digits` followed by
`copilot plugin update digits`. A Git push does not refresh existing chats.
Installing directly from a local path also works, but the CLI flags it as
deprecated. Dashboard and terminal changes use their own installer.

## Incremental self-improvement

`/digits:self-improve` reviews only the chats newer than the last successful run.
It writes an executive summary plus the exact edits it proposes, and nothing is
applied before you approve. After a validated success, including an approved
"no changes" review, the cursor moves to the window's frozen upper bound. Failed,
incomplete, rejected or cancelled runs never skip history, and each new window
replays a 24-hour overlap. `status` is read-only. An active reservation blocks
competing runs and is never reset automatically. The first baseline needs a
timestamp you agree on and an evidence artifact.

State lives in `~/.local/state/digits/self-improve/state.json`; proposals,
reports and completion records are private artifacts. The helper never collects
chats, edits files, posts, starts agents or creates schedules. Running the
command grants no permission to publish to Git, touch production, or refresh
other chats.

## Helpers, credentials and side effects

Skills always run helpers from the installed skill directory (the parent of the
installed `SKILL.md`), never from a checkout or a copied file.

| # | Helper (under `skills/`) | Side effects | Inputs it reads |
|---|---|---|---|
| 1 | `standup-update/fetch-github-activity.sh` | none | `gh` (must be logged in) plus `jq` |
| 2 | `standup-update/fetch-jira-activity.sh` | none | the Jira Cloud REST API, authenticated from a Keychain entry |
| 3 | `standup-update/run-scheduled.sh` | writes one dated draft plus a log into the output directory | launches `copilot -p` without supervision |
| 4 | `review-reactions/reaction_plan.py` | none; prints a plan | `gh pr view` |
| 5 | `draft-pr-sweep/pr_status.py` | none | GraphQL through `gh` |
| 6 | `update-shared-workflows/shared_refs.py` | edits workflow files, and only when `--write` is given | tags via `gh api`; local workflow files |
| 7 | `inter-env/inter_env.py` | private drafts and receipts; types into tmux only during an approved `send` | tmux, ps, lsof, saved session history |
| 8 | `self-improve/checkpoint.py` | the private checkpoint file | its own state file; the installed context |

`standup-update` pre-approves its read-only tools with an `allowed-tools` line in
Copilot CLI syntax. Those entries match no Claude Code tool, so there it asks for each
tool as your own settings require; to avoid the prompts, allow `Bash(gh:*)` and
your Atlassian MCP tools (`mcp__<server>__<tool>`) in your Claude Code
permissions.

### Jira helper

Requires bash, jq, curl and the macOS `security` tool. The site comes from the
second argument or `DIGITS_JIRA_SITE`; `DIGITS_JIRA_PRIORITY_LABEL` optionally
adds open issues with that label and marks them as priority. Credentials are
read from the Keychain item `digits-standup-jira`, which you create once in your
own terminal:

```bash
security add-generic-password -s digits-standup-jira -a jira \
  -w '{"email": "<you@example.com>", "api_token": "<api-token>"}'
```

The item name and the placeholders are not secrets. The secret reaches curl only
through stdin, never on a command line or in output. If interactive tracker
authentication fails, do not fall back to this helper. Its bounded search does
not replace a full ticket reconciliation.

### Scheduled runner

`run-scheduled.sh` is never installed or run by plugin installation; schedule it
yourself only if you want it. It deliberately passes both `--allow-all-urls` and
`--allow-all-tools` to `copilot -p`, so review that before scheduling it. Drafts
go to `DIGITS_STANDUP_DIR` (default `~/.local/state/digits/standup`), dated in
`DIGITS_STANDUP_TZ` (default: system local time). It refuses to run when today's
draft already exists, and it never submits or posts the update.

The helper tests use mocks and stubs; no live integration is needed.

Credentials, caches, drafts, receipts, logs, transcripts and private profiles
never enter this package.

### References

- Creating plugins for Copilot CLI: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/plugins-creating
- Copilot CLI plugin reference: https://docs.github.com/en/copilot/reference/copilot-cli-reference/cli-plugin-reference
- Jira enhanced JQL search: https://developer.atlassian.com/cloud/jira/platform/rest/v3/api-group-issue-search/#api-rest-api-3-search-jql-get
