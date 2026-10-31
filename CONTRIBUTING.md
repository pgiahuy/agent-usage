# Contributing

Thanks for looking. This is a small tool with a narrow job, so the bar for a
change is that it makes the readout more correct or easier to live with.

## Before you write code

Open an issue first for anything that changes behaviour, adds a setting, or
adds an agent. A short note about what you want to do saves the work of
building something the project then has to turn down. Bug reports need no
preamble: if the numbers are wrong, that is worth an issue on its own.

## Getting set up

There is nothing to install. The collector is Python 3.8 with the standard
library only, and the extension is GJS, which GNOME Shell provides.

```sh
git clone https://github.com/pgiahuy/agent-usage.git && cd agent-usage
./install.sh                 # installs into $HOME, no root
python3 -m unittest discover -s tests
```

Re-running `./install.sh` is how you load your changes, and it reloads the
panel indicator without a logout in most cases. `docs/hacking.md` explains
when a logout is still needed and why, along with the module layout and how
to add an agent.

## The checks

CI runs these, so run them before you push:

```sh
python3 -m unittest discover -s tests
ruff check daemon tests
shellcheck install.sh uninstall.sh build-deb.sh build-apt-repo.sh tools/doctor.sh bin/agent-usage.in
for f in extension/*.js; do node --check "$f"; done
glib-compile-schemas --strict --dry-run extension/schemas
```

The tests point every path the collector touches at a temporary directory and
talk only to local servers, so they never read your real tokens or logs. They
run on Python 3.8, 3.12 and 3.13.

A change to the collector wants a test. The place that bites hardest is
deduplication: Claude replays earlier messages into a resumed session's log and
Kimi writes both a per-turn and a per-session usage record, so counting either
one wrong roughly doubles the totals. If you touch `extract()` for an agent,
add a test with a replayed line.

## House style

- Comments explain why, not what. If a line needs a comment to say what it
  does, the line is the problem.
- No em-dashes anywhere, in code, comments, documentation or commit messages.
- Python: standard library only, `ruff.toml` names the rules, 100 columns.
- Never show a number the provider did not give. A reading whose window has
  rolled over is dropped, not zeroed, because what the new window holds is
  unknown until a fetch succeeds.
- Nothing that reads a token may follow a redirect, and nothing may rotate a
  token on the timed loop. `docs/hacking.md` has the reasoning.

## Commits and pull requests

One concern per commit. Write the subject in the imperative and lowercase,
under about 70 characters, and use the body to say why the change is right
rather than restating the diff. The existing log is the reference.

A pull request should say what it changes, what you ran, and anything you were
unsure about. Draft pull requests are welcome if you want a look before it is
finished.

## Adding an agent

Everything about one agent lives in `daemon/providers/<name>.py`. The fields
are documented in `daemon/providers/base.py`, and `docs/hacking.md` has the
checklist for wiring a new one into the registry and the preferences page.
Expect questions about how the agent's quota endpoint was found and how its
token is read, since both decide whether the readout can be trusted.

## Reporting a vulnerability

Do not open a public issue. [SECURITY.md](SECURITY.md) says where to send it.
