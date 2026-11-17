# Contributing

## Before you start

Open an issue before changing behaviour, adding a setting or adding an agent,
so the approach is agreed before the work is done. Bug reports need no
preamble: wrong numbers are worth an issue on their own.

## Setup

The collector is Python 3.8+ with the standard library only, and the extension
is GJS, which GNOME Shell provides. There is nothing else to install.

```sh
git clone https://github.com/pgiahuy/agent-usage.git && cd agent-usage
./install.sh                 # into $HOME; run it again to load your changes
```

[docs/hacking.md](docs/hacking.md) covers the code layout, how a UI change
reaches a running shell, and how to add an agent.

## Checks

CI runs these on Python 3.8, 3.12 and 3.13. Run them before you push:

```sh
python3 -m unittest discover -s tests
ruff check daemon tests
shellcheck install.sh uninstall.sh build-deb.sh build-apt-repo.sh tools/doctor.sh bin/agent-usage.in
for f in extension/*.js; do node --check "$f"; done
glib-compile-schemas --strict --dry-run extension/schemas
```

The tests never touch your real tokens or logs: every path points at a
temporary directory, and HTTP goes to local servers.

A change to the collector needs a test. A change to an agent's `extract()`
needs one with a replayed log line, because miscounted replays double the
totals.

## Rules

- Never show a number a provider did not give. A reading whose window has
  passed is dropped, not zeroed.
- A request carrying a token never follows a redirect, and the timed loop
  never renews a token.
- Python: standard library only, 100 columns, the rules in `ruff.toml`.
- Comments say why, not what.
- No em-dashes anywhere.

## Commits and pull requests

One concern per commit. Write the subject in the imperative, in lowercase,
under about 70 characters, and use the body to say why.

Keep pull request descriptions short: what changes, what you ran, and what you
are unsure about. Drafts are welcome.

## Security

Report vulnerabilities privately, as described in [SECURITY.md](SECURITY.md).
