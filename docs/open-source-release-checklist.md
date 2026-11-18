# Open-source release checklist

Use this checklist before publishing a fork or derivative of Digits outside
the organization that maintains it. The status column records how Digits
itself was released.

## Blockers

| # | Item | Owner | Status |
|---|---|---|---|
| 1 | Choose a license, add a `LICENSE` file, and update the README status and the package metadata | Maintainer | Done: MIT (`LICENSE`) |
| 2 | Obtain the employer's approval for an open-source release, covering IP assignment, the contribution policy, and a trademark and name check on "Digits" | Maintainer | Done |
| 3 | Confirm consent and attribution for the workflow-skill ideas taken from another engineer's personal harness, and record it in [provenance](provenance.md) | Maintainer with the original author | Done: credited in [provenance](provenance.md#acknowledgements) |
| 4 | Publish into a new repository from fresh history: the clean-room history that starts at the specification commit, or a single new squashed commit. Never push the internal main history or other internal branches publicly | Maintainer | Done: published from the clean-room history |
| 5 | Run all guards with the maintainer's private-terms list and confirm they are clean on the exact commit to be published | Maintainer | Done |
| 6 | Have someone independent review all executable code: both installers, the launcher, the shell helpers, the dashboard extension, and the plugin extensions `session-done` and `digits-refresh`, paying particular attention to the broad unattended approvals granted by the standup-update scheduled runner `run-scheduled.sh` | Reviewer | Open: not yet done for the initial release |

## Verification on the exact commit to publish

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
DIGITS_PRIVATE_TERMS=/path/to/private-terms.txt python scripts/check_repository.py
python scripts/check_secrets.py
DIGITS_PRIVATE_TERMS=/path/to/private-terms.txt python scripts/check_publication.py --range HEAD
python -m unittest discover -s tests
python -m unittest discover -s plugin/skills/inter-env -p 'test_*.py'
for helper in plugin/skills/standup-update/*.sh; do bash -n "$helper"; done
node --test copilot/extensions/env-dashboard/*.test.mjs plugin/com.github.copilot/extensions/*/*.test.mjs
```

A term list can miss things, so also search by hand for internal host names,
organization names, people and internal links. Examine `git log` and the tags
of the repository that will actually be published.

## Recommended before announcing

- **Experimental dependencies**: the README states that the dashboard and the
  extensions rely on experimental Copilot CLI extension APIs and lists the CLI
  versions that were verified.
- **Maintenance**: add a `CODEOWNERS` file, turn on private vulnerability
  reporting and security advisories, and fill in the enforcement contact in
  the code of conduct.
- **Public CI**: confirm that CI runs on public hosted runners and needs
  neither internal secrets nor self-hosted machines.
- **Fresh-account walkthrough**: following only the README, install the
  dashboard, plugin and context into a brand-new user account, then uninstall
  them.
- **Clean-room record**: the rebuild record in `docs/provenance.md` is complete and the result of the
  similarity scan is recorded.
- **Optional**: add screenshots or a short recording of the dashboard.
