# ai-usage

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
- Claude Code and/or Kimi Code signed in. Neither is required; a tool that is
  not installed simply does not get a block.

The terminal view (`ai-usage`) works anywhere, GNOME or not.

## Signing in

There is nothing to configure and no API key to paste. The collector reads the
token each tool already wrote when you signed in to it:

- `~/.claude/.credentials.json`: Claude Code refreshes this as you use it, so
  it is normally valid and the Claude bars are always there.
- `~/.kimi-code/credentials/kimi-code.json`: Kimi's access token lives 15
  minutes, so the Kimi bars appear only if you have run `kimi` recently. The
  collector deliberately does not refresh it: rotating the refresh token could
  invalidate the one Kimi Code itself holds.

Token counts come from the session logs and are there either way.

Both tools can be pointed at a different directory, and the collector follows
them: `CLAUDE_CONFIG_DIR` for Claude Code, `KIMI_CODE_HOME` for Kimi Code. A
systemd user service does not inherit your shell's environment, so set those
in `~/.config/environment.d/ai-usage.conf` rather than in `.bashrc`:

```
CLAUDE_CONFIG_DIR=/data/claude
KIMI_CODE_HOME=/data/kimi-code
```

Signing in to Claude Code with an API key rather than a subscription leaves no
OAuth token behind, so that tool gets no quota bars, because the quota endpoint
measures a plan, and an API key is not one.

## Install

```sh
git clone https://github.com/pgiahuy/ai-usage.git && cd ai-usage
./install.sh
```

Then **log out and back in once**. GNOME Shell scans for new extensions only
when the session starts, and there is no reload call any more, so a fresh
install cannot appear before that. The installer says so when it applies.

Re-running `./install.sh` is also the upgrade path; after an upgrade the
extension reloads with `gnome-extensions disable ai-usage@local && gnome-extensions enable ai-usage@local`.

Everything lands under `$HOME`, with no root and no system packages:

```
~/.local/share/ai-usage/                            collector
~/.local/bin/ai-usage                               command
~/.local/share/gnome-shell/extensions/ai-usage@local/   extension
~/.config/systemd/user/ai-usage.service             service
~/.cache/ai-usage/                                  readings, ring icons
```

## Install system-wide (.deb)

For a shared machine, or to install with the package manager instead of a
script:

```sh
./build-deb.sh                              # -> dist/ai-usage_1.0.0_all.deb
sudo apt install ./dist/ai-usage_1.0.0_all.deb
```

The package puts the collector in `/usr/share/ai-usage`, the command in
`/usr/bin`, the extension in `/usr/share/gnome-shell/extensions`, and the user
service in `/usr/lib/systemd/user`. `postinst` runs `systemctl --global enable
ai-usage.service`, so every user's session starts the collector at login.

Two things stay per-user, because they are per-user by nature:

```sh
gnome-extensions enable ai-usage@local   # once per user, after one logout
```

Do not run `install.sh` as well, or you end up with two copies, one in
`/usr` and one in `$HOME`, and the `$HOME` one wins on `PATH`.

Removal is `sudo apt remove ai-usage`. That leaves each user's
`~/.cache/ai-usage`, which is just cached readings and icons.

### `apt install ai-usage`, from your own repository

For plain `apt install ai-usage`, and `apt upgrade` picking up new versions
along with everything else, the package has to live in a repository the
machine trusts. `build-apt-repo.sh` builds one into `docs/apt/`, which GitHub
Pages can serve directly from the `main` branch (Settings → Pages → Source:
main, folder `/docs`).

Once, to publish:

```sh
gpg --quick-generate-key "Your Name <you@example.com>" default default 5y
./build-apt-repo.sh
git add docs/apt && git commit -m "publish 1.0.0" && git push
```

The signature is the point of the key: it is how apt knows the package came
from you and not from whoever else could reach the host. Skip it and every
user has to write `[trusted=yes]` in their source line, which switches that
check off.

Then each user adds the source once:

```sh
sudo install -d /etc/apt/keyrings
curl -fsSL https://pgiahuy.github.io/ai-usage/apt/ai-usage.asc \
  | sudo tee /etc/apt/keyrings/ai-usage.asc > /dev/null
echo "deb [signed-by=/etc/apt/keyrings/ai-usage.asc] https://pgiahuy.github.io/ai-usage/apt stable main" \
  | sudo tee /etc/apt/sources.list.d/ai-usage.list
sudo apt update && sudo apt install ai-usage
```

Shipping a new version is `VERSION=1.1.0 ./build-apt-repo.sh` and another
commit. Note that the repository URL must not contain spaces: apt splits
`sources.list` lines on whitespace, so a path with one in it fails with a
confusing "Release file not found".

The other route is a Launchpad PPA, which builds from source you upload and
gives Ubuntu users `add-apt-repository ppa:you/ai-usage`. It needs a Launchpad
account and a signed source upload; the `.deb` here is the same artifact.

## Uninstall

```sh
./uninstall.sh          # leaves the cache
./uninstall.sh --purge  # removes it too
```

## Terminal

```
$ ai-usage
 CLAUDE
   5-hour           █░░░░░░░░░   3%   resets Thu 04:09
   Weekly           ██░░░░░░░░  18%   resets Tue 16:00
   Today              670.3M tokens     3.0k req
   ...

$ ai-usage --json     # same reading, machine readable
$ ai-usage --daemon   # the collector, in the foreground
$ ai-usage --tray     # AppIndicator fallback, needs PyGObject
```

## How it works

Two pieces, on purpose:

- **The collector** (`daemon.py`) does all the work: it parses the logs, calls
  the quota endpoints, renders the ring icons, and writes one small JSON file
  to `~/.cache/ai-usage/state.json`.
- **The extension** only reads that file and draws it. The compositor never
  parses hundreds of megabytes of jsonl and never makes a network call; if the
  collector dies, the panel says so instead of freezing the shell.

Refresh rates: token counts every **20s**, quota percentages every **5 min**,
and the popup redraws the moment the state file changes (it watches the file,
so an open popup updates itself). The refresh button forces a quota call
immediately, without waiting out the five minutes.

The quota interval is deliberately not shorter. Anthropic's usage endpoint
rate-limits hard; on a 429 the collector backs off from 60s up to 15 minutes,
and during that time there is no live reading at all.

Kimi does not document a usage endpoint, so the collector probes a short list
of candidate paths once, remembers the one that answers with percentages, and
uses only that afterwards. The raw payload is kept at
`~/.cache/ai-usage/kimi-raw.json`, which is the only record of what that API
actually sends.

## Data and privacy

The collector reads, locally:

- `~/.claude/.credentials.json` and `~/.kimi-code/credentials/kimi-code.json`,
  for the access token needed to ask each provider about your own quota;
- `~/.claude/projects/**/*.jsonl` and `~/.kimi-code/sessions/**/wire.jsonl`,
  for token counts.

It talks to exactly two hosts, `api.anthropic.com` and `api.kimi.com`, and
writes only inside `~/.cache/ai-usage`. Nothing is sent anywhere else, and no
telemetry is collected.

It never refreshes or rotates a token. Kimi's access token lives 15 minutes, so
outside an active kimi session it is usually expired and the Kimi bars fall
back to "no quota"; rotating the refresh token to avoid that could invalidate
the one Kimi Code itself holds and break its login.

## Configuration

There is no settings UI. The knobs are constants at the top of the files:

| What | Where |
| --- | --- |
| Refresh intervals | `LOCAL_EVERY`, `QUOTA_EVERY` in `daemon.py` |
| Shared cache TTL, backoff | `QUOTA_FRESH_S`, `_BACKOFF_MIN/MAX` in `usage_core.py` |
| Colour thresholds | `_TIERS` in `ring.py` |
| Which Claude limits are shown | `_CLAUDE_SKIP_KINDS` in `usage_core.py` |
| Card width, bar width, spin speed | top of `extension/ui-1.js` and `stylesheet.css` |

After editing a Python file: `systemctl --user restart ai-usage`.

## Troubleshooting

**Nothing in the panel.** The extension needs one logout after the first
install. Then `gnome-extensions info ai-usage@local` should say ACTIVE, and
`journalctl --user -u org.gnome.Shell@wayland -n 50` shows any load error.

**"ai-usage daemon is not running".** `systemctl --user status ai-usage`, and
`journalctl --user -u ai-usage -n 50` for the reason.

**Claude says "rate limited".** Expected after too many forced refreshes; it
clears itself. The last known reading stays on screen, marked as such.

**Kimi says "token expired".** Run any kimi command; the bars fill in within
five minutes.

**`--tray` fails to start.** That fallback needs PyGObject, which pyenv and
conda interpreters do not have. Point the `PY=` line of `~/.local/bin/ai-usage`
at `/usr/bin/python3`.

## Development

`extension.js` is only a loader. GJS caches an imported module by URI for the
life of the shell process, so editing a UI file in place does nothing until the
next logout. The loader imports the highest-numbered `ui-<n>.js` it finds, so
the way to ship a UI change to a running session is to copy the file to the
next number and toggle the extension:

```sh
cd ~/.local/share/gnome-shell/extensions/ai-usage@local
cp ui-1.js ui-2.js && $EDITOR ui-2.js
gnome-extensions disable ai-usage@local && gnome-extensions enable ai-usage@local
```

`stylesheet.css` is re-read on every enable, so CSS-only changes need no copy.
Two revisions can be live in one process, which is why the `GObject.registerClass`
names carry the revision number.

## License

MIT. See [LICENSE](LICENSE).
