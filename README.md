# agent-usage

[![CI](https://github.com/pgiahuy/agent-usage/actions/workflows/ci.yml/badge.svg)](https://github.com/pgiahuy/agent-usage/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GNOME Shell 48+](https://img.shields.io/badge/GNOME%20Shell-48%2B-4a86cf.svg)](https://release.gnome.org/)

Claude Code and Kimi Code usage in the GNOME top bar: how much of each plan is
spent, when it resets, and how many tokens went out today and over the week.

Percentages are **consumed**, from each provider's own API, not an estimate
derived from the logs. Token counts come from the local session logs, so they
keep working when a quota endpoint does not.

| Tool | Bars | Source |
| --- | --- | --- |
| Claude Code | 5-hour, Weekly | `GET api.anthropic.com/api/oauth/usage` |
| Kimi Code | 5-hour, Plan | `GET api.kimi.com/coding/v1/usages` |
| both | today / 7 days tokens, request counts | local `*.jsonl` session logs |

Bars turn amber at 75% consumed and red at 90%.

## Requirements

- GNOME Shell 48 or newer for the panel indicator (developed and tested on 50)
- Python 3.8+, standard library only
- systemd user session (optional: without it, run the collector yourself)
- Claude Code and/or Kimi Code signed in

Nothing needs configuring and there is no API key to paste: the collector
reads the token each tool already wrote when you signed in. A tool that is not
signed in shows token counts only, with no quota bars; one that is not
installed is not shown at all. Signing in to Claude Code with an API key
rather than a subscription also gives no quota bars, because the quota
endpoint measures a plan.

The Extensions app has the optional settings, under Agent Usage: how often
quota is checked, which tools to show, the popup layout (tiles, compact or
large numbers) and the panel style (ring or text).

The terminal view (`agent-usage`) works anywhere, GNOME or not.

## Install

```sh
git clone https://github.com/pgiahuy/agent-usage.git && cd agent-usage
./install.sh
```

Then **log out and back in once**: GNOME Shell only looks for new extensions
when the session starts, and offers no way to load one later.

Re-running `./install.sh` is the upgrade path, and it needs no logout: it
reloads the panel indicator itself. The exception is an update that changes
`extension.js`, `metadata.json` or whether there is a preferences page, which
GNOME Shell reads only at login; the installer says so when that happens.

Everything lands under `$HOME`, no root and no system packages:

```
~/.local/share/agent-usage/                            collector
~/.local/bin/agent-usage                               command
~/.local/share/gnome-shell/extensions/agent-usage@pgiahuy.github.io/   extension
~/.config/systemd/user/agent-usage.service             service
~/.cache/agent-usage/                                  readings, ring icons
```

For a system-wide install with a `.deb`, or publishing to an APT repository,
see [docs/packaging.md](docs/packaging.md).

## Uninstall

```sh
./uninstall.sh          # leaves the cache
./uninstall.sh --purge  # removes it too
```

The indicator leaves the panel at once, no logout needed.

## Terminal

```
$ agent-usage
 CLAUDE
   5-hour           █░░░░░░░░░   3%   resets Thu 04:09
   Weekly           ██░░░░░░░░  18%   resets Tue 16:00
   Today              670.3M tokens     3.0k req
   ...

$ agent-usage --json     # same reading, machine readable
$ agent-usage --daemon   # the collector, in the foreground
```

## Data and privacy

The collector reads, locally, `~/.claude/.credentials.json` and
`~/.kimi-code/credentials/kimi-code.json` for the access tokens, and
`~/.claude/projects/**/*.jsonl` and `~/.kimi-code/sessions/**/wire.jsonl` for
token counts. It talks to `api.anthropic.com` and `api.kimi.com`, follows no
redirects with a token attached, and writes inside `~/.cache/agent-usage`,
which it keeps private to you. No telemetry.

The timed refresh never touches a token. Only the popup's Refresh button
renews an expired one: for Kimi, the collector refreshes it at `auth.kimi.com`
the way `kimi` itself does, under Kimi's own lock and never while `kimi` is
running, and writes the new token back to Kimi's credentials file; for Claude,
it runs `claude auth status`, then if needed one minimal `claude -p` prompt,
so Claude Code renews its own token.

If a tool keeps its data elsewhere, the collector follows `CLAUDE_CONFIG_DIR`
and `KIMI_CODE_HOME`. A systemd user service does not read `.bashrc`, so set
them in `~/.config/environment.d/agent-usage.conf`:

```
CLAUDE_CONFIG_DIR=/data/claude
KIMI_CODE_HOME=/data/kimi-code
```

## Troubleshooting

```sh
./tools/doctor.sh      # read-only; says what is wrong and the command to fix it
```

**Nothing in the panel.** Run the line above first. Almost always one of
three things: the session has not been restarted since the install, user
extensions are switched off for the whole session
(`gsettings get org.gnome.shell disable-user-extensions` returns true), or
GNOME Shell is outside the versions `extension/metadata.json` declares, in
which case the shell refuses to load the extension and reports nothing.

**"agent-usage daemon is not running".** `systemctl --user status agent-usage`, and
`journalctl --user -u agent-usage -n 50` for the reason.

**Claude says "rate limited".** Expected after too many forced refreshes; it
clears itself. The last known reading stays on screen, marked as such.

**Kimi says "token expired".** Press Refresh in the popup. If it says "kimi is
running", the token renews on its own the next time that session talks to
Kimi.

## Contributing

Bug reports and pull requests are welcome. [CONTRIBUTING.md](CONTRIBUTING.md)
has the checks to run and the house style;
[docs/hacking.md](docs/hacking.md) has the module layout, the refresh and
backoff rules, how to ship a UI change to a running shell, and how to add an
agent. Everyone taking part is expected to follow the
[code of conduct](CODE_OF_CONDUCT.md).

Found a security problem? Please report it privately, not in an issue:
[SECURITY.md](SECURITY.md).

## Changes

[CHANGELOG.md](CHANGELOG.md), and the current release number is in
[VERSION](VERSION).

## License

MIT. See [LICENSE](LICENSE).
