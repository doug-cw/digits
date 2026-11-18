---
name: token-usage
description: Read-only report of AI token usage and estimated list-price cost per task (chat), project, branch, environment, model or day, from local Claude Code transcripts. Use for "how much did this task cost", "token usage this week", "AI spend per project", "cost by model" or a cost line for a status report.
user-invocable: true
---

# Token usage and estimated cost

Usage: `/digits:token-usage [this chat | <period>] [by task|project|branch|env|model|day]`

## Run the helper

Substitute the real absolute parent directory of this installed `SKILL.md` for
`<absolute-skill-directory>`, never the current checkout or the literal placeholder:

```sh
python3 "<absolute-skill-directory>/token_usage.py" report --since <YYYY-MM-DD> --by task --format table
```

- **Window.** Default to the last seven days. "Today", "this week" and named dates map
  to `--since` and `--until` (UTC; a bare `--until` date covers the whole day).
- **This chat.** Pass `--session <this session id>` with no `--since`.
- **Grouping.** `--by` takes `task` (one chat, shown with its title), `project`,
  `branch` (`<folder>@<git branch>`), `env` (folder the chat started in), `model`
  or `day`; repeat it to combine, for example `--by project --by model`.
- **One environment.** Add `--root <environment root>`.
- **Projects** come from the private rules file
  `~/.config/digits/context/token-projects.json` (see
  `examples/private-bindings/token-projects.example.json` in the Digits source).
  Without it every request is `unassigned`; offer the example, never invent rules.
- Use `--format json` (the default) when another skill consumes the numbers; it is
  paged with `--limit` and `--offset`.

## Report

Lead with the total for the window, then the table. State plainly that:

- Costs are estimates at the public list prices in the bundled `rates.json`
  (source URL and retrieval date are in the output). Subscriptions, negotiated
  rates and batch discounts are not reflected; treat the figure as
  API-equivalent spend, not an invoice.
- Only Claude Code transcripts on this machine are counted. Copilot CLI chats,
  other machines and transcripts Claude Code has already cleaned up
  (`cleanupPeriodDays`, 30 days by default) are missing, so totals are a floor.
- Rows marked `*` include models with no rate; name them and do not guess a price.

## Stay read-only

Do not edit transcripts, settings, rates or project rules, and do not post the
report anywhere unless the user asks; reader-facing copies follow the writing page.
