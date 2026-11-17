# Hacking

## How it works

- **The collector** (`daemon/`, `agent-usage --daemon`) does all the work:
  it scans the session logs, asks the quota endpoints, draws the ring icons,
  and writes one JSON file, `~/.cache/agent-usage/state.json`.
- **The extension** (`extension/`) only reads that file and draws it. GNOME
  Shell never parses logs or makes a network call, and if the collector stops,
  the panel says so instead of hanging.

Token counts update every 20 seconds. Quota is checked every 5 minutes by
default (`quota-interval`), and each agent's header shows how old its figures
are. The popup watches `state.json`, so it redraws as soon as the file changes,
and re-reads it every 60 seconds regardless. Refresh asks for quota at once.

Anthropic's usage endpoint rate-limits hard. On a 429 the collector backs off,
doubling from 60 seconds up to 15 minutes, and keeps the last reading on screen.

Kimi's usage endpoint is undocumented. The collector probes a short list of
paths, remembers the one that returns percentages, and caches only the usage
part of the reply in `~/.cache/agent-usage/kimi-raw.json`; for the rest, which
holds account and billing ids, it keeps only the key names.

A request carrying a token never follows a redirect, since `urllib` would copy
the `Authorization` header to the new host. The cache directory is mode 0700.

## Layout

```
daemon/
  daemon.py       the loop: which agents, when to ask, writing state.json
  cli.py          the terminal view
  collector.py    one log scanner per agent, kept between passes
  scan.py         incremental jsonl scanning, totals per day and per model
  quota.py        the quota flow shared by every agent: cache, token, renewal, backoff
  cache.py        small JSON files in ~/.cache/agent-usage
  net.py          HTTP without redirects, and short failure reasons
  settings.py     the user's settings, read from GSettings
  paths.py        where each agent and this tool keep their files
  fmt.py          formatting of numbers, times and bars, and ISO timestamp parsing
  ring.py         the panel's ring icon
  providers/      one module per agent; the registry is __init__.py
extension/
  extension.js    a loader that imports the newest ui-<n>.js
  ui-<n>.js       the panel indicator and the popup
  prefs.js        the preferences page
  stylesheet.css  the styles, with light-style overrides at the end
  schemas/        the GSettings schema
tests/            unittest, standard library only
```

## Adding an agent

Everything about one agent lives in `daemon/providers/<name>.py`, which builds
a `Provider`. `providers/base.py` documents each field:

- where its session logs are, and how to turn one log line into
  `(epoch, model, dedup_key, inp, out, cache_read, cache_write)`;
- how to read its access token, ask its quota API, and renew the token, or
  return the reason it cannot.

Then add it to `PROVIDERS` in `providers/__init__.py`, to `TOOLS` in
`extension/prefs.js`, and to the ids in the `hidden-tools` description in the
schema. The extension draws whatever `state.json` lists, so it needs nothing
else.

Get deduplication right. Claude Code replays earlier messages into a resumed
session's log, and Kimi Code writes both a per-turn and a per-session usage
record; counting either wrongly doubles the totals. Give `extract()` a dedup
key and a test with a replayed line.

## Tokens

The collector uses the token each agent saved at sign-in:

- `~/.claude/.credentials.json`. Claude Code renews it as you use it, so it is
  usually valid.
- `~/.kimi-code/credentials/kimi-code.json`. Kimi's access token lasts 15
  minutes, so on the timed loop Kimi's bars appear only if `kimi` ran recently.

Only Refresh renews a token (`renew=True` in `quota.fetch()`); the timed loop
never does. Refresh renews an expired token. It also renews a token the server
refuses with a 401 before it has expired, once, and retries only if the stored
token actually changed.

- **Kimi** (`renew()` in `providers/kimi.py`) refreshes at `auth.kimi.com` the
  way Kimi Code does. The refresh token rotates, so a refresh racing Kimi Code's
  own would sign the user out. It refuses while any `kimi` process runs, takes
  Kimi's own lock (a proper-lockfile directory at
  `~/.kimi-code/oauth/kimi-code.lock`) and re-stamps it every 2 seconds while
  held, since proper-lockfile treats a lock untouched for 5 seconds as stale.
  It writes only while it still owns the lock, atomically, at mode 0600. A
  refused token that has not expired is left alone: it expires within 15
  minutes and is renewed then.
- **Claude** (`renew()` in `providers/claude.py`) never acts as Claude Code. It
  runs `claude auth status`, then if needed one `claude -p` prompt on haiku
  with no tools, MCP servers or saved session, so that Claude Code renews its
  own token.

## Configuration

The settings live in the extension's GSettings schema,
`extension/schemas/org.gnome.shell.extensions.agent-usage.gschema.xml`, and
are edited in the Extensions app. The collector reads the same keys by running
`gsettings get` once per key on each pass (`settings.py`), and falls back to
the defaults when that fails.

| Key | Used by | Default |
| --- | --- | --- |
| `quota-interval` | collector: minutes between quota checks, 2 to 60 | `5` |
| `hidden-tools` | both: agent ids to leave out (`claude`, `kimi`) | `[]` |
| `popup-layout` | extension: `tiles`, `compact` or `numbers` | `tiles` |
| `pill-style` | extension: `ring`, or `text` for an initial and a percentage | `ring` |

The layouts are functions in `LAYOUTS` in `ui-<n>.js`. Each fills one agent's
block under a shared header, so Refresh, the age label and the last-known note
behave the same in all of them.

A hidden agent disappears from the popup at once, and the collector stops
scanning and checking it on its next pass. An agent whose home directory does
not exist is left out the same way.

Other tunables are constants:

| What | Where |
| --- | --- |
| Token count interval | `LOCAL_EVERY` in `daemon.py` |
| Cache freshness, backoff | `FRESH_S`, `_BACKOFF_MIN`, `_BACKOFF_MAX` in `cache.py` |
| Colour thresholds | `_TIERS` in `ring.py` |
| Claude limits not shown | `_SKIP_KINDS` in `providers/claude.py` |
| Card and bar widths, spinner speed | the top of `ui-<n>.js`, and `stylesheet.css` |

After editing a Python file, run `systemctl --user restart agent-usage`.

## Tests

```sh
python3 -m unittest discover -s tests
ruff check daemon tests
shellcheck install.sh uninstall.sh build-deb.sh build-apt-repo.sh tools/doctor.sh bin/agent-usage.in
```

The tests point every path the collector uses at a temporary directory and
talk to local HTTP servers, so they never read real tokens or logs. CI also
parses the JavaScript, compiles the schema and builds the `.deb`.

## Shipping a UI change

GJS caches an imported module by its URI for the life of the shell, so editing
a UI file in place has no effect until the next login. `extension.js` therefore
imports the highest-numbered `ui-<n>.js` it finds, and a UI change reaches a
running shell under the next number.

`install.sh` does this on an upgrade: if the UI file changed, it installs it as
one number above the highest present and toggles the extension; if only
`stylesheet.css` changed, it toggles without renaming, since the stylesheet is
re-read on enable. In the repository the UI file keeps its number. By hand:

```sh
cd ~/.local/share/gnome-shell/extensions/agent-usage@pgiahuy.github.io
cp ui-3.js ui-4.js && $EDITOR ui-4.js
gnome-extensions disable agent-usage@pgiahuy.github.io
gnome-extensions enable agent-usage@pgiahuy.github.io
```

Two revisions can be loaded in one process, which is why the GObject class
names in `ui-<n>.js` include the revision number.
