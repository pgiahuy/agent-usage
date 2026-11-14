# Hacking

## How it works

Two pieces, on purpose:

- **The collector** (`daemon/`, run as `agent-usage --daemon`) does all the
  work: it parses the logs, calls the quota endpoints, renders the ring icons,
  and writes one small JSON file to `~/.cache/agent-usage/state.json`.
- **The extension** (`extension/`) only reads that file and draws it. The
  compositor never parses hundreds of megabytes of jsonl and never makes a
  network call; if the collector dies, the panel says so instead of freezing
  the shell.

Refresh rates: token counts every **20s**, quota percentages every **5 min** by
default (`quota-interval`, see Configuration), and the popup redraws the moment
the state file changes (it watches the file, so an open popup updates itself).
The refresh button forces a quota call immediately, without waiting out the
interval.

The quota interval is deliberately not shorter. Anthropic's usage endpoint
rate-limits hard; on a 429 the collector backs off from 60s up to 15 minutes,
and during that time there is no live reading at all.

Kimi does not document a usage endpoint, so the collector probes a short list
of candidate paths once, remembers the one that answers with percentages, and
uses only that afterwards. The usage part of the raw reply (`usage`, `usages`,
`limits`) is kept at `~/.cache/agent-usage/kimi-raw.json`, the only record of
what that API actually sends; the rest of the reply carries account and
billing ids, so only its key names are kept.

Requests that carry a token never follow a redirect: urllib would copy the
`Authorization` header to wherever the redirect points, any host, even plain
http. A redirect comes back as an HTTP error instead. The cache directory is
kept at mode 0700.

## Layout

```
daemon/
  daemon.py       the loop: which agents, when to ask, state.json
  cli.py          the terminal view (agent-usage, agent-usage --json)
  collector.py    one log scanner per agent, kept alive between passes
  scan.py         incremental jsonl scanning, per-day and per-model totals
  quota.py        the quota flow every agent shares: cache, token, renew, backoff
  cache.py        small JSON files in ~/.cache/agent-usage
  net.py          HTTP without redirects
  settings.py     the user's choices, read from GSettings
  paths.py        where each agent and this tool keep their files
  fmt.py          number, time and bar formatting
  ring.py         the panel's ring icon
  providers/      one module per agent; the registry is __init__.py
extension/
  extension.js    loader only: imports the newest ui-<n>.js
  ui-<n>.js       the panel pill and the popup
  prefs.js        the Preferences page
  schemas/        the GSettings schema
tests/            unittest, standard library only
```

## Adding an agent

Everything about one agent lives in `daemon/providers/<name>.py`, which builds
a `Provider` (`providers/base.py` documents each field):

- where its session logs are, and how to turn one log line into
  `(epoch, model, dedup_key, inp, out, cache_read, cache_write)`;
- how to read its access token, how to ask its quota API, and how to renew an
  expired token (or return a reason when it cannot be renewed).

Then add it to `PROVIDERS` in `providers/__init__.py`, and its id to the
`hidden-tools` description and the `TOOLS` list in `extension/prefs.js`. The
extension draws whatever `state.json` lists, so it needs no other change.

The part that bites is deduplication: Claude replays earlier messages into a
resumed session's log, and Kimi writes both a per-turn and a per-session usage
record. Counting either wrong roughly doubles the totals, so give `extract()`
a dedup key and a test with a replayed line.

## Tokens

The collector reads the token each agent wrote when you signed in:

- `~/.claude/.credentials.json`: Claude Code refreshes this as you use it, so
  it is normally valid and the Claude bars are always there.
- `~/.kimi-code/credentials/kimi-code.json`: Kimi's access token lives 15
  minutes, so on the timed loop the Kimi bars appear only if you have run
  `kimi` recently.

An explicit Refresh renews an expired token (`renew=True` in `quota.fetch()`);
the timed loop never does.

- Kimi (`providers/kimi.py`, `renew()`): the refresh token rotates, so a
  refresh racing Kimi Code's own would leave one side holding a dead token and
  the user signed out. It therefore refuses while any `kimi` process runs,
  takes the lock Kimi itself uses (proper-lockfile, i.e. a mkdir of
  `~/.kimi-code/oauth/kimi-code.lock`), backs off if Kimi holds it, re-reads
  the file under the lock, and writes the result back atomically with mode
  0600. proper-lockfile treats a lock untouched for 5s as stale, so the
  request timeout keeps the hold under that. The OAuth host must be https.
- Claude (`providers/claude.py`, `renew()`): the collector never refreshes as
  Claude Code. It runs `claude auth status`, and if that leaves the token
  expired, one `claude -p ok` on haiku with no tools, no MCP servers and no
  saved session. That call can take a while, and the daemon loop waits for it.

## Configuration

User settings live in the extension's GSettings schema,
`extension/schemas/org.gnome.shell.extensions.agent-usage.gschema.xml`, and are
edited in the Extensions app (`prefs.js`). The installer and `build-deb.sh`
compile the schema into the extension's own `schemas/` directory.

The collector reads the same keys, so there is one store and nothing to keep
in sync. It is standard library only, so it shells out to
`gsettings --schemadir <extension>/schemas get` once per key, so twice on
every 20s pass (`settings.py`), and falls back to the built-in default when
that fails.

| Key | Used by | Default |
| --- | --- | --- |
| `quota-interval` | collector: minutes between quota checks (2 to 60) | 5 |
| `hidden-tools` | both: agent ids left out (`claude`, `kimi`) | `[]` |
| `popup-layout` | extension: `tiles`, `compact` or `numbers` | `tiles` |
| `pill-style` | extension: `ring`, or `text` (initial and percentage) | `ring` |

The layouts are renderer functions in one UI module (`LAYOUTS` in
`ui-<n>.js`), not separate files: the file number is the reload mechanism, not
a menu. Each fills one agent's block under the shared header, so the refresh
button, the stale note and the no-quota case behave the same in all of them.

A hidden agent is dropped twice over. The collector stops scanning its logs and
calling its quota API on its next 20s pass (`settings.visible()`), and the
extension filters it out of what it draws the moment the setting changes, so
the switch does not wait for that pass. An agent whose home directory
(`~/.claude`, `~/.kimi-code`, or the env override) does not exist is left out
the same way, since it has never run here. Every tool in `state.json` carries
an `id` for this.

Everything else is still a constant at the top of a file:

| What | Where |
| --- | --- |
| Token count interval | `LOCAL_EVERY` in `daemon.py` |
| Shared cache TTL, backoff | `FRESH_S`, `_BACKOFF_MIN/MAX` in `cache.py` |
| Colour thresholds | `_TIERS` in `ring.py` |
| Which Claude limits are shown | `_SKIP_KINDS` in `providers/claude.py` |
| Card width, bar width, spin speed | top of the newest `extension/ui-<n>.js` and `stylesheet.css` |

After editing a Python file: `systemctl --user restart agent-usage`.

## Tests and checks

```sh
python3 -m unittest discover -s tests          # every test, no network
ruff check daemon tests                        # ruff.toml names the rules
shellcheck install.sh uninstall.sh build-deb.sh build-apt-repo.sh tools/doctor.sh bin/agent-usage.in
```

The tests point every path the collector touches (cache, `~/.claude`,
`~/.kimi-code`, the GSettings schema) at a temporary directory, and the HTTP
ones talk to local servers, so they never read your real tokens or logs. CI
runs all of the above on Python 3.8, 3.12 and 3.13, plus a .deb build.

## Shipping a UI change

`extension.js` is only a loader. GJS caches an imported module by URI for the
life of the shell process, so editing a UI file in place does nothing until the
next logout. The loader imports the highest-numbered `ui-<n>.js` it finds, so
the way to ship a UI change to a running session is to copy the file to the
next number and toggle the extension.

`install.sh` does this itself on an update: when the UI differs from the
installed one, it installs it as one number above the highest already there,
then runs disable/enable; when only `stylesheet.css` differs, it keeps the
name and still toggles. In the repo the UI file keeps whatever number it has.
By hand, while working on it:

```sh
cd ~/.local/share/gnome-shell/extensions/agent-usage@pgiahuy.github.io
cp ui-2.js ui-3.js && $EDITOR ui-3.js
gnome-extensions disable agent-usage@pgiahuy.github.io && gnome-extensions enable agent-usage@pgiahuy.github.io
```

`stylesheet.css` is re-read on every enable, so CSS-only changes need no copy.
Two revisions can be live in one process, which is why the `GObject.registerClass`
names carry the revision number.
