# Build your own Digits

This is a practical guide for an engineer, or an agent working on an
engineer's behalf, who wants a harness in the Digits style shaped around their
own organization.

Digits began as one engineer's workbench at a single company. This repository
keeps the mechanisms and drops the company details. The guide explains each
mechanism, why it exists, and how to rebuild or adapt it for a different
stack, host or team, so you can take the ideas without inheriting another
person's habits wholesale.

## 1. What Digits is

Digits is a pattern rather than a product. It has five layers, and each one is
useful on its own.

| Layer | Problem it solves | Generic implementation here |
|---|---|---|
| Workbench | With many chats running at once, it is hard to tell which one is waiting for you | Ten separate full clones (`~/left_thumb` … `~/right_pinky`) as windows of one tmux session; an extension reports each chat's state (for example WORKING, NEEDS YOU, YOUR TURN) to a dashboard with timers, clickable entries and an attention hotkey |
| Context harness | Agents forget conventions, and long instruction files get skimmed or crowd out the real task | A short always-loaded bootstrap (boundaries plus a route table) and topic pages opened by intent; installed as immutable content-addressed releases with hash-bound adoption and rollback |
| Private bindings | Shared source must not carry the real names of accounts, profiles, channels or repository lists | Non-secret Markdown kept on the machine under `~/.config/digits/context/`; the bootstrap points to it; it is never exported |
| Workflow plugin | Multi-step chores (review feedback, rebases, investigations, standups, coordination across chats) get done unevenly or unsafely | Skills with approval gates and dry-run defaults, standard-library helpers with mocked tests, and two lifecycle extensions (refresh in place; finish and reset) |
| Learning loop | The same correction keeps coming back | Each correction becomes a routing fixture, then a topic edit, then checks, then a reviewed install; the proposal-first `self-improve` command reviews recent chats using a private cursor |

Three principles hold the layers together:

1. **Approval comes in stages and is never assumed.** Planning, preview,
   publication, release, rollout, recovery and external messages each need
   their own permission. None of them is implied by passing CI, a merge, an
   older handoff or a recommendation from another agent.
2. **Load little, route the rest.** Only the bootstrap loads automatically.
   Everything else is reached through intent or symptom routes (for example
   "wrong role", "missing release bump" or "empty MCP search") that lead to the
   page an agent must read before a specific consequential step.
3. **Prose is backed by deterministic checks.** Fixtures, link and metadata
   tests, installer ownership tests, the three guards and mocked helper tests
   make the guidance regression-testable. A keyword test is a guard, not proof
   of how a model behaves.

## 2. Decide what you actually need

Have the agent interview you, or answer these questions yourself. Store the
answers in private bindings, never in shared source.

| Question | Why it matters | Where the answer goes |
|---|---|---|
| Which host or hosts: Copilot CLI, Claude Code, Codex, something else? | It fixes where instruction files live, the skill or plugin format, and the extension or hook API | Installer constants and the host adapter ([section 6](#6-porting-to-another-agent-host)) |
| How many chats do you run at the same time? | It decides whether the workbench is worth it | The launcher's list of environments |
| Which outside systems do agents use (code host, tracker, chat, observability, warehouse, cloud)? | Each one needs a recipe, a route and rules for denied access | `context/integrations/` plus bindings |
| What must never happen without you (merges, deployments, posts people will read, production queries, credential changes)? | These become bootstrap boundaries and skill gates | `context/bootstrap.md` and the individual skills |
| What is expensive or dangerous to get wrong in your domain? | Each one gets a domain page naming the step it must come before | `context/domains/*.md` |
| Which identifiers must stay private: tenants, accounts, people, channels, the repository list? | They go into bindings and into the private-terms denylist | `~/.config/digits/` |
| Which recurring workflows waste the most time? | They are skill candidates; start with one or two | `plugin/skills/` |

Start small. Most of the value comes from a solid bootstrap, a couple of
domain pages and one well-guarded skill.

## 3. Build plan for an agent

Work through the phases strictly in order. Each phase ends with an acceptance
check that must pass before the next one starts. Never write live
configuration without showing a preview and getting explicit consent.

### Phase 0 — inventory and boundaries

- Read the existing instruction files, skills and settings without changing
  anything.
- Build a preservation map with two columns, the earlier guidance and where it
  now lives, so nothing disappears unnoticed.
- List the approval boundaries and private identifiers gathered in
  [section 2](#2-decide-what-you-actually-need).

**Accept when** the user has signed off on both the boundary list and the
preservation map.

### Phase 1 — bootstrap

- Write `context/bootstrap.md` in three parts. Aim for 1,000–2,000 words and
  treat 3,000 words as a warning sign.
  - (a) Rules that always apply: staged approval; the line between interacting
    with humans and with bots; what to do when access is denied (stop, name
    what is missing, never switch credentials); tool discovery, where schemas
    are never guessed; checking which environment and repository you are in;
    verifying real outcomes instead of proxies; and communication style.
  - (b) A route table with the columns intent or symptom | page | before,
    keyed on what the user said or what failed rather than on file names.
  - (c) A handful of reminders that come up often and are expensive to
    forget.

**Accept when** a trivial unrelated request, such as renaming a variable,
would not trigger any topic-page read, as shown by the Phase 4 fixtures.

### Phase 2 — topic pages

- One subject per page, under 200 lines.
- Start every page with a metadata header carrying the title and five
  markers:

  ```markdown
  # Page title

  Use when: <the intents or symptoms that should lead here>
  Scope: <what this page covers and what it does not>
  Sources: <where the facts come from>
  Reviewed: YYYY-MM-DD
  Recheck: <when or why to review it again>
  ```

- Put the decision procedure first and the reasoning after it. Add examples
  only when they help, and vary them.
- Keep live inventories in bindings or in a private fork; the shared
  repository ships a template with invented rows.

**Accept when** every page carries all five markers, every relative link
resolves, and every page can be reached from the bootstrap.

### Phase 3 — installer

- No symlinks and no copying by hand.
- Preview by default; write only with `--apply`.
- Replace `{{HOME}}`, `{{CONTEXT_ROOT}}` and `{{PRIVATE_ROOT}}` with absolute
  paths, and turn every relative link into a `file:///` URL with an absolute
  path. Abort on unknown placeholders or dead links before anything is
  written.
- Install content-addressed, immutable releases so that chats already running
  keep working links.
- Keep a private ownership receipt with hashes and modes, and refuse files the
  installer does not own. Adopting a hand-written instruction file requires the
  exact hash shown in the preview (`--adopt-sha256`).
- Rollback restores the previous entry and keeps older releases for as long as
  anything still points at them.
- Out of scope: settings, MCP authentication, terminal configuration,
  repositories and schedules.
- `context_install.py` and its tests already do all of this; reuse them.

**Accept when** tests in temporary homes cover a preview that writes nothing,
hash-bound adoption, update, rollback, refusal on local edits, refusal of
symlinks, and hostile receipt paths.

### Phase 4 — routing fixtures and evaluation

- Create `tests/fixtures/context-routing.json` with de-identified prompts, the
  pages they should reach and the expected behavior. The static test only shows
  that routes exist and are mentioned.
- For behavioral evaluation:
  - isolate every run: a throwaway home and workspace, read-only tools, and no
    MCP, writes, shell or outbound messages;
  - run both model families several times with held-out paraphrases;
  - judge by the files actually read and the actions actually attempted, not
    by what the model says about itself;
  - include controls: unrelated tasks that should load nothing extra, and
    denied-access cases that should stop rather than retry with other
    credentials.

**Accept when** the controls pass and every routed case opens the expected page
before the gated action.

### Phase 5 — private bindings

- Create `~/.config/digits/context/` with files such as
  `tool-and-repo-bindings.md` and `data-warehouse-bindings.md`, modeled on
  `examples/private-bindings/`.
- Record non-secret facts together with where they came from (which profile,
  warehouse size, channel, mandatory ticket fields). Never record credentials.
- A missing binding pauses only the action that needs it.

**Accept when** neither the installer nor the source reads, copies or exports
these files, and running the guards on the shared source with
`DIGITS_PRIVATE_TERMS` set reports no private terms.

### Phase 6 — skills

- Pick the one or two biggest time sinks.
- For each skill:
  - frontmatter `name` identical to its directory, and a `description` that
    names its triggers;
  - settings resolved from explicit arguments, then bindings, then a single
    batched question; identifiers are looked up live, never guessed;
  - side effects gated by dry-run or plan-first defaults, the exact outbound
    text shown before sending, state such as the PR head rechecked before every
    write, and force-pushes pinned to the recorded previous head;
  - helpers limited to the standard library, locating files relative to the
    installed skill, and tested with mocks;
  - written-down non-goals, for example no automatic merges, no replies to
    people without approval, and no creating schedules.

**Accept when** the mocked helper tests pass and installing the plugin into a
temporary host home yields exactly one registration per skill.

### Phase 7 — workbench (optional)

- Only worth it for heavy parallel use.
- Use one full clone per environment; worktrees share refs and invite
  collisions.
- Code running inside the host (an extension or event hooks) writes each
  chat's state into a tmux option on its pane. Never scrape it from the
  screen.
- Lifecycle events drive the state; polling only refreshes the display.
- The launcher is idempotent: it keeps panes, refuses clashing windows and
  never restarts chats.
- Install with a preview-first installer that keeps a receipt and uninstalls
  cleanly.

**Accept when** tmux tests on an isolated socket cover window order, click
targets and every state transition.

### Phase 8 — learning loop

When the user corrects the agent:

1. Extract the lasting, non-sensitive lesson and discard the transcript.
2. Add a focused fixture.
3. Change the smallest existing topic, folding the lesson into an existing
   rule rather than adding a new global one.
4. Run the checks, preview, apply, then preview again and expect zero
   changes.
5. Report the source edit, the install, publication and the refresh of other
   chats as four separate results.

Periodic review uses a proposal-first command and a private "reviewed-through"
cursor. The cursor moves only after the user approves the proposals (or
explicitly approves making none) and validation passes.

**Accept when** a repeated correction has a fixture, a minimal topic edit and a
clean second preview.

## 4. What the generic open-source version looks like

```text
README.md                quick start for each component, safety model
LICENSE                  MIT
bin/                     launcher and Markdown viewer
terminal/                dashboard tmux configuration and optional fragments
copilot/                 dashboard extension and settings example
context/                 bootstrap, topic pages and version
examples/private-bindings/  templates for local, non-secret bindings
plugin/                  Agent Plugins 1.0 package: skills and extensions
mcp/                     integration recipes and placeholder configuration
scripts/                 repository and secret guards
tests/                   Python tests and routing fixtures
docs/                    this guide, provenance and the release checklist
install.py               dashboard installer
context_install.py       context installer
.github/                 CI, marketplace manifest, contributing, security, code of conduct
spec/                    functional specification for the clean-room build
```

### Kept, generalized, removed

Compared with its private predecessor:

| Area | Kept as is | Generalized | Removed |
|---|---|---|---|
| Workbench | Launcher, states, timers, hotkeys, `md-view` | Receipt location (`~/.local/state/digits/`) | Nothing |
| Context | Loader contract, installer, metadata markers, fixtures | Bootstrap boundaries; pages on GitHub delivery, engineering decisions, continuity, infrastructure-as-code lifecycle, writing and MCP diagnosis; one generic data-warehouse domain; an issue-tracker page; a repository map reduced to a template | Organizational account families, tenants, warehouse names, repository inventories, the list of review bots, release-dispatch steps, summaries of controlled documents |
| Plugin | The nine skills that needed no organization data: `assess-and-address`, `challenge-pass`, `done`, `draft-pr-sweep`, `inter-env`, `investigate`, `rebase-pr`, `self-improve`, `summarize` | `request-review`, `review-reactions` and `update-shared-workflows`, which now read channel, reactions and organizations from arguments or bindings; the standup drafter, renamed `standup-update`, with a configurable tracker site | Hardcoded channels, tracker site IDs, people, organization product names |
| Integrations | The recipe principles | An example configuration without credentials | One company's authentication proxy and token helper |
| Guards | The source and secret checks | A new, optional private-terms guard driven by a local denylist | Nothing |

### Configuration model

| Kind of value | Where it lives |
|---|---|
| Generic rules and mechanisms | The shared repository |
| Facts specific to one organization, such as required fields, channels, repositories or accounts | Private bindings, or `context/domains` in a private fork |
| In-flight work: approvals, receipts, the PR head being acted on, task state | That session's artifacts; never long-term memory or source |
| Credentials | The OS keychain or the host's built-in authentication; never Markdown and never command-line arguments |

### Versioning

- The plugin and marketplace versions change together, and a test enforces
  it.
- The context library has its own version in `context/version.json`, bumped
  with every reviewed context change.
- Installs are content-addressed, so a version bump cannot break chats that
  are already running. Idle chats pick up new instructions, skills and
  extensions through the `digits-refresh` extension.

## 5. Customization recipes

- **New domain** (worked example: deploying to Kubernetes). Create
  `context/domains/kubernetes.md` with all five metadata markers and name the
  step it must come before, for example before pushing manifests to a shared
  cluster. Add its row to the route table, and add two or three fixtures, at
  least one of them negative. Keep cluster names and contexts in bindings.
- **New skill.** Add `plugin/skills/<name>/SKILL.md` with a standard-library
  helper and a mocked test, hook the test into CI, and raise the plugin and
  marketplace versions together.
- **New integration.** Write a recipe in [mcp/README.md](../mcp/README.md)
  saying where the credential lives, which harmless read verifies it and what a
  denial looks like. Then add an access-denial row to the MCP diagnosis page.
- **Different tracker or chat product.** Change only the bindings and the
  recipe; the skills are already written in terms of a configured channel and
  an issue tracker.

## 6. Porting to another agent host

Nothing in the design depends on one host, but the way instructions and skills
are loaded differs between hosts and keeps changing. Check each host's current
official documentation before trusting a path or format.

| Aspect | Copilot CLI (this reference) | What to check on other hosts (always against their current docs) |
|---|---|---|
| Always-loaded user instructions | `~/.copilot/copilot-instructions.md` ([documentation](https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-custom-instructions)) | Claude Code's [memory files and their import syntax](https://code.claude.com/docs/en/memory); Codex's [`AGENTS.md` discovery](https://developers.openai.com/codex/guides/agents-md) |
| Skills loaded on demand | `SKILL.md` files inside a plugin | The skill mechanisms of Claude Code and [Codex](https://developers.openai.com/codex/skills) |
| Lifecycle hooks and extensions | The experimental extension SDK used by the dashboard, `digits-refresh` and `session-done` | Whatever hooks the host offers; without an equivalent, leave the dashboard layer out |
| Packaging | An Agent Plugins 1.0 marketplace | The host's own plugin format, or plain directories plus an installer |

The dashboard already has a Claude Code port: `claude/hooks/env_dashboard.py`
publishes the same pane options from Claude Code hooks (see the README). A port only touches the installer's target path and the packaging. The
bootstrap, pages, bindings, fixtures and guards carry over unchanged, and one
prompt text serves every model family; do not fork it per model.

## 7. Anti-patterns

- Growing the global instruction file with every correction.
- Pulling in every topic page up front through `@` imports or discovery
  globs.
- Putting account IDs, channel names or people in shared source, even as
  "examples".
- Treating an empty tool search as proof that an integration is gone, or
  retrying a refused action with other credentials.
- Letting a skill take the next consequential step (posting, merging,
  deploying, marking ready) just because the previous one went well.
- Symlinking live configuration into a repository, or exporting a dump of a
  home directory.
- Mandating multi-agent fan-out, or making productivity claims nobody can
  verify, instead of reviewing in proportion to risk.
- Declaring success because of a keyword test, a route the model reported
  about itself, or a CI job that was skipped.

## 8. Publishing your own

Work through the [open-source release checklist](open-source-release-checklist.md).
In short:

- choose a license and get your employer's sign-off;
- obtain attribution and consent for any borrowed material;
- publish from a fresh history, never from the history of an internal branch;
- run every guard with your own private-terms list, and review executable
  extensions and hooks as code.
