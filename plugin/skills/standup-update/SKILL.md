---
name: standup-update
description: Builds your daily standup or progress update in your configured format by cross-checking earlier updates, recent work chats, issue-tracker data and live GitHub state. Use for any request to write, draft or generate a standup, daily update, check-in or progress update.
allowed-tools: shell(gh:*), shell(./fetch-jira-activity.sh:*), shell(./fetch-github-activity.sh:*), atlassian-searchJiraIssuesUsingJql, atlassian-getJiraIssue, atlassian-atlassianUserInfo, atlassian-getAccessibleAtlassianResources, atlassian-search, atlassian-fetch, session_store_sql
license: MIT
---

# Standup update

Usage: `/digits:standup-update [format] [since date] [output path]`

This skill only reads sources and writes a local draft. Posting or submitting
happens only when the user explicitly asks (step 9). The helpers sit next to this
`SKILL.md`: replace `<absolute-skill-directory>` with the real absolute parent
directory of this installed `SKILL.md` (never the current checkout, a personal
skills directory, or the literal placeholder). Credentials, earlier updates and
chat history come from outside the plugin.

## Configuration

Resolve values from (1) command arguments, (2) the private bindings file
`~/.config/digits/context/tool-and-repo-bindings.md`, (3) one batched ask
(the Digits bootstrap's Communication rule: one `ask_user` or `AskUserQuestion` call, or one numbered list when the decisions do not fit) for everything still missing. Never guess site, cloud or project IDs.

| Key | Default |
|---|---|
| `standup_format` | `yesterday-today-blockers` |
| `standup_output_dir` | `~/.local/state/digits/standup` |
| `standup_timezone` | the machine's local zone |
| `standup_field_limit` | about 1,200 characters for the progress field |
| `standup_ticket_links` | `bare` (or `plain`) |
| `issue_tracker_site` | ask, or produce a GitHub-only draft |
| `standup_priority_query` | no ranking |

| Format | Field labels, in order |
|---|---|
| `yesterday-today-blockers` | **Yesterday** (progress since the previous update), **Today** (next step per active workstream), **Blockers** |
| `four-field` | **What are you assigned?** (active workstreams), **Progress since the last update**, **When will it be ready to test?**, **Blockers** |
| custom | the bound labels in their given order; map progress, plan or readiness, and blockers onto them |

## Style

1. Group by workstream; with two or more themes, put a plain-text heading line
   above each group's bullets.
2. Every bullet names its ticket and/or PR; never "worked on some tickets". With
   `bare`, leave ticket keys unlinked (`PROJ-123`) because standup tools expand
   them and a hand-made link can get wrapped twice. Write PRs as `repo #N`; add a
   bare PR URL only for work with no ticket.
3. Progress bullets start with old state, arrow, new state, an em dash, then the
   reference: `In Progress → Done/Merged — repo #71: ...`. Work still waiting on
   reviewers has one state and no arrow: `In Review (draft)` or
   `In Review — repo #1: ...`. Leave out anything else that did not change.
4. Add one clause on why it mattered (root cause, impact or reasoning).
5. The baseline is the state in the prior update, confirmed by dated evidence. If
   the workflow status stayed put but real work moved, describe concrete before
   and after conditions (`Validation pending → Isolated-dev validation passed —
   ...`). Unknown earlier state is written `Prior state unknown` followed only by
   a verified change; never make one up.
6. Put identifiers readers need (tables, flags, files) in backticks.
7. Readiness and blocker fields always say something ("None", "once merged",
   "next week"). A dependency the user owns is "None blocking" plus its name.
8. Never truncate with "...more"; shorten to fit instead.
9. Bold only the field labels. Flat one-line `- ` bullets; no nesting, Markdown
   links, headings, filler or repeated questions.

Budget: progress holds at most six bullets and about 1,200 characters of source
text plus one heading line per group (or `standup_field_limit`; expanded ticket
keys may render up to three times longer). Assignment or plan: three lines at
most. Readiness and blockers: one short line each. A ticket appears once in
progress. Reviews, newly filed follow-ups and small items merge into one "Also:"
line or are dropped. Aim for two to four workstreams.

## Steps

1. **Earlier updates first.** Find the two or three newest distinct drafts in
   this conversation, then fill gaps with `session_store_sql` on `turns`:
   assistant responses from the last 7 days mentioning the first field label or
   the `digits/standup/` path, newest first, at most 3 rows (widen to 14 days
   only if needed). Cloud data can lag: if a known recent update is missing,
   rerun with `source: "local"`, `LIKE`, and a date-prefix filter on the
   timestamp. Merge cloud/local duplicates by content and trust the date written
   inside each update, since local turn timestamps can belong to the next turn.
   If a reply only gave a file path, open that draft (and, if needed, the newest
   two or three dated files in the output directory); it still counts. On
   Claude Code use `python3 "<absolute-skill-directory>/../self-improve/session_history.py"
   turns --role assistant --since <date> --grep '<first field label>' --grep
   digits/standup/ --limit 3` instead (a turn matches if it contains either term); it reads local history only. Capture
   open themes, last reported status, promised readiness and blockers. Drafts
   show what was said, not that work happened or was submitted. If none exist,
   say so instead of inventing a baseline.
2. **Since date.** Unless the user names another cadence, use the previous
   working day in the configured zone (Friday on a Monday, otherwise yesterday).
   It bounds the activity window only; older open work still counts.
3. **Recent work chats (mandatory).** Query the `sessions` table across every
   environment, not just this checkout: updated within 7 days, newest first, at
   most 60 rows; repeat with `source: "local"` and a date-prefix filter if
   expected chats are missing or summaries look stale. On Claude Code run the
   same helper's `sessions --since <date> --limit 60`, then `turns --session
   <id> --limit 6`. A missing or generic
   summary is not proof of no work. For likely work sessions read checkpoints or
   the newest few turns, both user and assistant text, because corrections,
   pauses and ownership calls often live only in user turns. Go further back only
   to settle an open decision or contradiction. Skip personal or unrelated
   chats. Never carry live task state across environments; never resume or
   modify another session.
   Keep a small per-workstream ledger in session state (never durable memory):
   ticket/PR links; previously reported state; latest chat decision with its
   session/turn; observed implementation or runtime evidence with its date; next
   action and owner; blocker; disposition (active, awaiting review, deferred,
   superseded, completed, uncertain). Work without a fresh ticket or PR update
   still gets a row. Trace replacements: a closed draft may have been dropped,
   not finished. A planned schedule is not a running job. Summaries are leads;
   confirm material claims.
4. **Issue tracker** (Jira as the reference; other trackers follow the same
   evidence rules).
   - Interactive (preferred): discover the tracker tools first. Get the cloud ID
     by matching the configured site in `getAccessibleAtlassianResources`; never
     invent it. Query issues assigned to the user and updated in the last N days
     (N = days since the prior update, at least 1) with summary, status, updated,
     type and assignee. Because `updated` also moves for automation and
     colleagues, look up the user's account ID with `atlassianUserInfo` and add
     an `issuekey IN updatedBy(...)` query bounded by the since date and today.
     Tickets only filed, not started, go in one "Filed follow-ups" line. When
     `standup_priority_query` is set, run it, use `statusCategory` to tell open
     from done, treat its rank as priority, and order workstreams by their
     best-ranked open item. Open items on that list remain current work without
     recent activity unless the user paused them, but being listed is not
     progress. Read descriptions of the main issues for the "why". For tickets
     left open in earlier updates or chats, fetch current status and meaningful
     recent comments even outside the window, skipping automated access-request
     noise. Recent comments and chat decisions beat stale descriptions. Confirm
     the assignee before carrying a ticket forward. With only generic
     search/fetch tools, use the identifiers they return. Report coverage gaps.
   - Headless: only with an explicitly configured and approved credential path,
     run `bash "<absolute-skill-directory>/fetch-jira-activity.sh" <days> <site>`.
     It reads the secret from the Keychain over stdin, never arguments, and marks
     label-matching open items with `priority` (no ranking).
   - An authentication or permission failure stops tracker access only; the
     read-only draft continues. Say which reconnect is needed and mark ticket
     status as unverified. Never switch credentials and never use the Keychain
     helper as a fallback in an interactive session. With no tracker configured,
     rely on GitHub and chats and say so.
5. **GitHub.** Run `bash "<absolute-skill-directory>/fetch-github-activity.sh" <date>`
   for the user's recently updated PRs (title, URL, state, `reviewDecision`,
   `isDraft`, body); use the body's overview for the "why". Reviews for
   colleagues count as work: search PRs the user reviewed that were updated since
   the date (number, title, url, author, state, repository; at most 30), drop PRs
   the user authored (login from `gh api user`), and, because that search matches
   PR updates rather than review times, confirm each review's timestamp through
   the PR reviews endpoint; never report an old review again. Group new reviews
   in one "Reviews" bullet. Find commits pushed without PR activity with a commit
   search by the user since the date (at most 50); attach commits to their PRs
   and mention leftovers only when substantive. Use `gh pr view` for live state
   of carried-forward or replacement PRs. A PR closed without merging is not
   Done; an approved draft is not merge-ready; a fresh update timestamp alone is
   not new work. Report helper failures as gaps.
   5a. **Incidents.** If an incident-management integration exists, collect the
   window's incidents and alerts where the user was responder or commander and
   lead with them (link, role, outcome); otherwise skip this step.
6. **Reconcile into a delta.** Authority by claim: live GitHub for PR state; the
   user's latest explicit decision for ownership, pauses and superseded work;
   time-stamped run evidence for runtime results; the tracker for ticket status;
   ties go to the newer date. A ticket and its PRs are one item. A source that
   failed or was not queried means "not checked", never "nothing happened", and
   is listed under limitations. Keep implementation, validation, release,
   deployment and recovery distinct; isolated-environment results say nothing
   about production. Designs, proposals and approvals are not executed work.
   Re-verify earlier blockers. Active themes appear in assignment, plan and
   readiness; progress lists only substantive changes plus items in review. Omit
   backlog and paused or deferred work; drop completions already reported.
7. **Render fields.** Assignment/plan names every still-active workstream (items
   in review and open priorities included), one line each. Readiness gives each
   workstream an evidence-backed answer, with dates only if current evidence
   commits to them. Blockers are "None" or a concrete list.
8. **Last evidence pass, then save.** Check that every progress bullet has a
   reference, a before → after prefix, a concrete change and a ledger row.
   Measure (do not estimate) each field against its budget. Account for every
   previously open theme. The newest user correction wins; do not revive cleared
   blockers; planned schedules, skipped CI and merges are not runtime proof.
   Save to `<standup_output_dir>/YYYY-MM-DD.md` using the configured local date,
   unless the caller gave a path. Never replace an existing file: interactive
   revisions take the next free `-v2.md`, `-v3.md`, and so on; an existing
   caller-supplied path stops the run. Fields come first, ready to paste; after a
   `---` line, list source limitations under `Not for posting:`. Re-read the
   saved file before reporting success. Reply with the absolute path, a
   percent-encoded `file:///` link, and `md-view '<absolute path>'` ready to run.
   Nothing is posted automatically; a human reads the update first.
9. **Posting, only on explicit request.** Show the exact text and destination and
   get approval. If a standup bot asks each field separately in a thread, answer
   one field per reply in the bot's order, with no AI-attribution header and
   exactly the user's overrides (such as "N/A"). Before each answer, reread the
   thread and confirm the bot's next prompt is there; if about a minute passes
   without it, stop and hand control back. Do not repost or try to repair a
   stalled thread. Mention any trailer text the integration adds automatically,
   and afterwards confirm the update was recorded.

## Optional headless runner

`<absolute-skill-directory>/run-scheduled.sh` drafts today's update unattended
(see the plugin README for its broad approvals). Nothing installs or schedules
it; it never posts or submits.
