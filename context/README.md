# Digits context library

Use when maintaining this shared context, adapting it for an organization, or looking for a topic the bootstrap does not route to.
Scope: personal agreements that hold across repositories; a repository's own contributor rules stay in that repository.
Sources: the reviewed agreements collected here, plus the vendor and host documentation linked below.
Reviewed: 2026-11-16.
Recheck: after any change to this source, the host, a workflow, or a private binding.

## Loading contract

- The single maintained source of always-on context is [bootstrap.md](bootstrap.md).
  The installer, `context_install.py` in the repository root, generates
  `~/.copilot/copilot-instructions.md` from it and copies every other page into a release
  directory whose name is a content hash. Once written, a release is never changed.
  With `--host claude` it writes `~/.claude/digits/CLAUDE.md` instead, which Claude Code
  loads only where it is linked in as a folder's `CLAUDE.md`, or imported with
  `@~/.claude/digits/CLAUDE.md`.
- At install time relative links are rewritten as absolute `file:///` links, and three
  placeholders are substituted: home, context root and private root (each is the
  upper-case name wrapped in two pairs of curly braces). Any other upper-case token in
  doubled braces stops the install. So the checked-in pages stay portable, and only the
  installed copy contains real local paths.
- Updates and rollbacks leave earlier topic snapshots in place, so a path that a running
  chat already received still opens. A private catalog keeps those retired versions under
  installer ownership.
- Nothing except the bootstrap is loaded automatically. Topic pages must never live where
  the host discovers instructions, must never be bulk-included with `@` imports, and no
  one keeps a second, hand-edited bootstrap.
- Routing is by meaning: the bootstrap table pairs an intent or symptom with a page and
  with the step that should wait for it. There is no vector index and no routing agent;
  an agent opens an extra page only when the first one names it as a prerequisite.

## Where facts live

| Kind of fact | Home |
|---|---|
| Lasting, generic rules and procedures | This library, after review |
| Machine-local facts that are not secret, for example the shell, profile, account, channel, issue project, required fields or list of repositories | Private bindings in `~/.config/digits/context` |
| Who owns what right now, approvals, PR heads, deployments, receipts | Session or workstream artifacts |
| Credentials, keys, tokens | Never in any of these; only in the platform's secret store |

There are two binding files, `tool-and-repo-bindings.md` and
`data-warehouse-bindings.md`; fictional starting points live in
`examples/private-bindings/` at the repository root. Each fact in a binding says where
and when it was verified, and bindings never hold credentials. The installer does not
copy, export or overwrite bindings, and a binding never grants permission for anything.
A missing binding only holds up the connection or step that needs it.

## Authoring contract

- Each page other than the bootstrap opens with five metadata lines, in this order:
  `Use when`, `Scope:`, `Sources:`, `Reviewed:`, `Recheck:`.
- Put a brief decision procedure first; add reasoning and a few varied examples only
  where they earn their place. Keep to one subject per page.
- The tests enforce a limit of 200 lines per file. Aim for a bootstrap of roughly 1,000
  to 2,000 words: the tests warn past 3,000 and fail past 10,000. Watch the installed
  size as well, since absolute links are longer than the relative ones in source.

Starting template for a page:

```markdown
# <Page title>

Use when <intents or symptoms>.
Scope: <what the page covers, and what it does not authorize>.
Sources: <where the rules come from>.
Reviewed: <YYYY-MM-DD>.
Recheck: <what to confirm live before relying on it>.

## Decision procedure

1. <Establish identity and scope.>
2. <Check cheap, authoritative evidence.>
3. <Say when to stop, and who approves the consequential step.>

## Rationale, pitfalls, and examples

- <Why the rule exists, how it goes wrong, and a short example.>
```

Link between pages with relative links; the installer refuses any link whose target file
does not exist. Spell local paths with the home or private-root placeholder rather than
a real user directory.

## Promotion rules

- A lesson travels this path: first a small regression fixture, then an edit to the
  right topic, then green checks, and finally a reviewed install.
- The bootstrap only gains a reminder that matters in nearly every task or that is
  very costly to forget. Inventories and step-by-step procedures go into pages.
- Do not keep appending fresh corrections to the global instructions, and do not copy
  policy into host memory. Strip identifying details from real cases before turning
  them into fixtures.
- When asked to "remember this in Digits", follow the
  [source-first procedure](workflows/harness-maintenance.md#explicit-shared-memory-updates-source-first).
- Changing source, installing it, publishing it to Git, and refreshing other chats are
  four separate events. Say plainly which of them took place.
- Wide-ranging retrospectives are the job of `/digits:self-improve`.

## Customizing for an organization

1. Fork or vendor this source, and keep every public copy free of organization facts.
2. Copy each `examples/private-bindings/*.example.md` to `~/.config/digits/context/`,
   dropping `.example` from the name, and fill in values you have verified, each with
   its provenance.
3. Swap the invented repository-map rows for real ones in a private fork, or keep the
   real inventory in your bindings instead.
4. Start any new domain page from the template, then give the bootstrap a routing row
   with the intent, the page, and the step that waits for it.
5. Add de-identified cases to `tests/fixtures/context-routing.json` with the keys `id`,
   `prompt`, `routes` and `expected`. Include controls for unrelated tasks, whose
   `routes` list is empty; every route has to be a page the bootstrap links to.
6. Raise the version in `version.json`, run every check, preview the installer, and only
   then apply it.

## Verification

Run this from the repository root:

```sh
python3 -m unittest discover -s tests -p 'test_context.py'
```

It covers placeholder substitution, link resolution, page length and metadata, the
adopt/update/rollback cycle, and whether each fixture route is a real page that the
bootstrap links to.

Evaluating model behavior is a different job: it has to observe which files a model
actually opened and what it actually did, with controls for unrelated tasks and for
refused access. Keyword matches say nothing about behavior. Safe canary setups are
described on the [harness maintenance page](workflows/harness-maintenance.md).

Design references:

- Anthropic, context engineering for agents: https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents
- Claude Code memory and imports (useful as a contrast with how Copilot loads files): https://code.claude.com/docs/en/memory
- Codex AGENTS.md guide: https://developers.openai.com/codex/guides/agents-md
- Codex skills guide: https://developers.openai.com/codex/skills
- OpenAI evaluation best practices: https://developers.openai.com/api/docs/guides/evaluation-best-practices
- GitHub Docs, custom instructions for the Copilot CLI: https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions

Those documents informed the design, yet the host that is actually running decides what
gets loaded. A model running inside Copilot does not inherit the file-discovery behavior
of its maker's own tools.
