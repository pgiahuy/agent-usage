# Hacking

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

## Tokens

The collector reads the token each tool wrote when you signed in:

- `~/.claude/.credentials.json`: Claude Code refreshes this as you use it, so
  it is normally valid and the Claude bars are always there.
- `~/.kimi-code/credentials/kimi-code.json`: Kimi's access token lives 15
  minutes, so the Kimi bars appear only if you have run `kimi` recently.

The collector deliberately never refreshes the Kimi token: rotating the
refresh token could invalidate the one Kimi Code itself holds and break its
login.

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

## Shipping a UI change

`extension.js` is only a loader. GJS caches an imported module by URI for the
life of the shell process, so editing a UI file in place does nothing until the
next logout. The loader imports the highest-numbered `ui-<n>.js` it finds, so
the way to ship a UI change to a running session is to copy the file to the
next number and toggle the extension:

```sh
cd ~/.local/share/gnome-shell/extensions/ai-usage@pgiahuy.github.io
cp ui-1.js ui-2.js && $EDITOR ui-2.js
gnome-extensions disable ai-usage@pgiahuy.github.io && gnome-extensions enable ai-usage@pgiahuy.github.io
```

`stylesheet.css` is re-read on every enable, so CSS-only changes need no copy.
Two revisions can be live in one process, which is why the `GObject.registerClass`
names carry the revision number.
