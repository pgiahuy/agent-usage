# agent-usage

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

There is nothing to configure and no API key to paste: the collector reads the
token each tool already wrote when you signed in. A tool that is not signed in
shows token counts only, with no quota bars. Signing in to Claude Code with an
API key rather than a subscription also gives no quota bars, because the quota
endpoint measures a plan.

The terminal view (`agent-usage`) works anywhere, GNOME or not.

## Install

```sh
git clone https://github.com/pgiahuy/agent-usage.git && cd agent-usage
./install.sh
```

Then **log out and back in once**: GNOME Shell only looks for new extensions
when the session starts.

Re-running `./install.sh` is the upgrade path. After an upgrade, reload the
extension with:

```sh
gnome-extensions disable agent-usage@pgiahuy.github.io && gnome-extensions enable agent-usage@pgiahuy.github.io
```

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
$ agent-usage --tray     # AppIndicator fallback, needs PyGObject
```

## Data and privacy

The collector reads, locally, `~/.claude/.credentials.json` and
`~/.kimi-code/credentials/kimi-code.json` for the access tokens, and
`~/.claude/projects/**/*.jsonl` and `~/.kimi-code/sessions/**/wire.jsonl` for
token counts. It talks to `api.anthropic.com` and `api.kimi.com`, and writes
inside `~/.cache/agent-usage`. No telemetry.

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

**Nothing in the panel.** Log out once after the first install. Then
`gnome-extensions info agent-usage@pgiahuy.github.io` should say ACTIVE, and
`journalctl --user -u org.gnome.Shell@wayland -n 50` shows any load error.

**"agent-usage daemon is not running".** `systemctl --user status agent-usage`, and
`journalctl --user -u agent-usage -n 50` for the reason.

**Claude says "rate limited".** Expected after too many forced refreshes; it
clears itself. The last known reading stays on screen, marked as such.

**Kimi says "token expired".** Press Refresh in the popup. If it says "kimi is
running", the token renews on its own the next time that session talks to
Kimi.

**`--tray` fails to start.** That fallback needs PyGObject, which pyenv and
conda interpreters do not have. Point the `PY=` line of `~/.local/bin/agent-usage`
at `/usr/bin/python3`.

## Development

How the two pieces fit, the refresh and backoff rules, the tunable constants,
and how to ship a UI change to a running shell: [docs/hacking.md](docs/hacking.md).

## License

MIT. See [LICENSE](LICENSE).
