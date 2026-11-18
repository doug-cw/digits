---
name: review-reactions
description: Keep status reactions current on the user's own review-request messages in the configured team chat channel - one for comments from humans other than the PR author, one when every linked PR is approved, and one when every linked PR is merged. Plans as a dry run first and adds reactions only when the user approves. Use when asked to sync, refresh or check the status reactions on review requests.
user-invocable: true
---

# Review reactions

Usage: `/digits:review-reactions [window in days, default 7] [channel]`

Reviewers skim the review channel by reaction, so a reaction tells them at a
glance that a request already has comments, is approved, or has merged.

## Boundaries

- Additive only: never remove reactions, never post or edit messages, and
  never react to messages written by anyone else.
- Reactions are added only after approval of the dry-run plan in step 4.
- The reference chat integration is the Slack MCP server.
- Intermediate files go to `<session-files>` (the session workspace `files/`
  folder), never `/tmp` or a repository.

## Steps

### 1. Configuration and identity at run time

Do not hardcode channel, user or emoji IDs. Each setting comes from the
invocation, else the bindings file
`~/.config/digits/context/tool-and-repo-bindings.md`, else one batched ask
(the Digits bootstrap's Communication rule: one `ask_user` or `AskUserQuestion` call, or one numbered list when the decisions do not fit) covering everything still unknown:

| Key | Default |
|---|---|
| `review_channel` (shared with `request-review`) | ask |
| `review_reaction_feedback` | `speech_balloon,comment` |
| `review_reaction_approved` | `white_check_mark` |
| `review_reaction_merged` | `twisted_rightwards_arrows,merge,merged` |

In each emoji list the first name is the one added; the rest are aliases.

Identities:

- chat user ID: the Slack MCP's current user (`slack_read_user_profile` with no
  user, or the user shown in search results);
- channel ID: the configured name resolved with `slack_search_channels`;
- GitHub login: `gh api user --jq .login`.

If chat tooling is missing or unauthenticated, stop and name the setup that is
needed. Never switch credentials.

### 2. Read and normalize

Call `slack_read_channel` with `oldest` = now minus the window, `limit` 100,
and the detailed response format (so reactions are included); page until the
whole window is read. Ignore thread replies. Write only the user's top-level
messages to `<session-files>/review-messages.json` as an array of objects with:

- `ts` - the exact original string;
- `user`;
- `text` - complete, with every link intact;
- `reactions` - a list of `{"name": ...}` objects or plain strings.

### 3. Dry-run plan

```bash
python3 "<skill-dir>/reaction_plan.py" "<session-files>/review-messages.json" \
  --user-id <chat user ID> --author-login <GitHub login> --seconds <window * 86400> \
  [--feedback <list>] [--approved <list>] [--merged <list>]
```

The helper reads PRs with `gh` and never calls the chat tool. It plans roles in
the order feedback, approved, merged so reactions read left to right in
chronological order:

- **feedback** - a `COMMENTED` or `CHANGES_REQUESTED` review on any linked PR
  from a human who is not the PR author (bots and Copilot do not count);
- **approved** - every linked PR's review decision is `APPROVED`;
- **merged** - every linked PR is `MERGED`.

A post that already carries any configured alias counts as having that role's
reaction. Rows with status `Error` were not checked: report them, never guess.

### 4. Approve, then apply

Show one plain-text table with columns: post (its date plus PR links naming
their repositories), status, reactions needed, reactions missing. If nothing
is missing, say so and stop.

Check each emoji name with `slack_search_emojis` first, since workspaces define
different custom emoji; if a primary name is rejected, offer one of its
configured aliases. Ask once, in a batched ask, whether to apply. Add reactions
only after approval: call `slack_add_reaction` (channel ID, message `ts`, emoji
name) once per planned call, in plan order. An `already_reacted` error counts
as success; any other error stops the run and names the post.

### 5. Report

A closing table of reactions added, reactions already present, and rows
skipped or errored. Point out posts whose PRs were closed without merging so
the user can decide whether to add a thread note; the skill never posts that
note itself.
