# Contributing

## Before you start

Open an issue before changing behaviour, adding a setting or adding an agent,
so the approach is agreed before the work is done. Bug reports need no
preamble: wrong numbers are worth an issue on their own.

## Setup

The collector is Python 3.8+ and the extension is GJS, which GNOME Shell
provides, so running it needs nothing else. The checks below also need ruff,
shellcheck, node and `glib-compile-schemas` (libglib2.0-bin).

```sh
git clone https://github.com/pgiahuy/agent-usage.git && cd agent-usage
./install.sh                 # into $HOME; run it again to load your changes
```

[docs/hacking.md](docs/hacking.md) covers the code layout, how a UI change
reaches a running shell, and how to add an agent.

## Checks

Run these before you push:

```sh
python3 -W error::ResourceWarning -m unittest discover -s tests
ruff check daemon tests
shellcheck install.sh uninstall.sh build-deb.sh build-apt-repo.sh tools/doctor.sh bin/agent-usage.in
for f in extension/*.js; do node --check "$f"; done
glib-compile-schemas --strict --dry-run extension/schemas
```

CI runs the tests on Python 3.8, 3.12 and 3.13, the other checks once, and
builds the `.deb`. The tests point every token, log and cache path at a
temporary directory and send HTTP only to local servers.

A change to the collector needs a test, and a change to an agent's `extract()`
needs one with a replayed log line.

## Rules

- Never show a number a provider did not give. A reading whose window has
  passed is dropped, not zeroed.
- Do not remove a defence listed in [SECURITY.md](SECURITY.md) without saying
  why.
- Python: standard library only, 100 columns, the rules in `ruff.toml`.
- Comments say why, not what.
- No em-dashes anywhere.

## Commits and pull requests

One concern per commit. Write the subject as `type(scope): summary`, in the
imperative and lowercase, under about 70 characters, for example
`fix(scan): skip a half-written line`. Use the body to say why.

Add a line to the Unreleased section of [CHANGELOG.md](CHANGELOG.md) for
anything a user would notice.

Keep pull request descriptions short: what changes, what you ran, and what you
are unsure about. Drafts are welcome.

Contributions are accepted under the [MIT licence](LICENSE), and participation
is covered by the [code of conduct](CODE_OF_CONDUCT.md). Report
vulnerabilities privately, as [SECURITY.md](SECURITY.md) describes.
