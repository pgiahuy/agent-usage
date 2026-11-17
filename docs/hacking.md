# Hacking

## How it works

- **The collector** (`daemon/`, `agent-usage --daemon`) does all the work:
  it scans the session logs, asks the quota endpoints, draws the ring icons,
  and writes one JSON file, `~/.cache/agent-usage/state.json`.
- **The extension** (`extension/`) draws that file, and asks for a refresh by
  writing an empty trigger file. GNOME Shell never parses logs or makes a
  network call. If the collector stops, the panel keeps the last reading and
  its age keeps growing; with no `state.json` at all, it says the daemon is not
  running.

Token counts update every 20 seconds. Quota is checked every 5 minutes by
default (`quota-interval`), and each agent's header shows how old its figures
are. The popup watches `state.json`, so it redraws as soon as the file changes,
and re-reads it every 60 seconds regardless. Refresh asks for quota at once,
unless the last reading is under 30 seconds old or a backoff is in force.

Anthropic's usage endpoint rate-limits hard. On a 429 the collector backs off,
doubling from 60 seconds up to 15 minutes, and keeps the last reading on screen.

Kimi's usage endpoint is undocumented. The collector probes a short list of
paths, remembers the one that returns percentages, and keeps the usage part of
the last reply in `~/.cache/agent-usage/kimi-raw.json` for debugging.

The security-relevant rules, such as no redirects and the private cache
directory, are in [SECURITY.md](../SECURITY.md).

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
else. The ring and the panel badge use the limit whose label starts with
"5-hour"; an agent without one gets a grey dot and its token count.

Get deduplication right. Claude Code replays earlier messages into a resumed
session's log, and Kimi Code writes both a per-turn and a per-session usage
record; counting either wrongly doubles the totals. Give `extract()` a dedup
key and a test with a replayed line.

## Tokens

The collector uses the token each agent saved at sign-in:

- `~/.claude/.credentials.json`. Claude Code renews it as you use it, so it is
  usually valid.
- `~/.kimi-code/credentials/kimi-code.json`. Kimi's access token lasts 15
  minutes, so the timed loop refreshes Kimi's figures only while `kimi` has run
  in the last 15 minutes; otherwise the last reading stays, marked last known,
  until its window resets.

Only Refresh renews a token (`renew=True` in `quota.fetch()`): an expired one,
and, once, one the server refuses with a 401, retrying only if the stored token
changed.

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

After changing the collector, run `./install.sh`, which copies it and restarts
the service.

## Tests

The checks, and what CI runs, are in [CONTRIBUTING.md](../CONTRIBUTING.md).

## Shipping a UI change

GJS caches an imported module by its URI for the life of the shell, so editing
a UI file in place has no effect until the next login. `extension.js` therefore
imports the highest-numbered `ui-<n>.js` it finds, and a UI change reaches a
running shell under the next number.

`install.sh` does this on an upgrade: if the UI file changed, it installs it
under a number above every one present and toggles the extension; if only
`stylesheet.css` changed, it toggles without renaming, since the stylesheet is
re-read on enable. In the repository the UI file keeps its number. By hand,
copy the installed `ui-<n>.js` to `ui-<n+1>.js`, edit that, and toggle:

```sh
cd ~/.local/share/gnome-shell/extensions/agent-usage@pgiahuy.github.io
n=$(ls ui-*.js | tr -dc '0-9\n' | sort -n | tail -1)
cp "ui-$n.js" "ui-$((n + 1)).js" && $EDITOR "ui-$((n + 1)).js"
gnome-extensions disable agent-usage@pgiahuy.github.io
gnome-extensions enable agent-usage@pgiahuy.github.io
```

Two revisions can be loaded in one process, which is why the GObject class
names in `ui-<n>.js` include the revision number.
