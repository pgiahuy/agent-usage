# Changelog

Notable changes per release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

Everything below has landed on `main` since 1.0.0 and is not in a release yet.

### Changed

- **The project is now `agent-usage`, renamed from `ai-usage`.** That covers
  the extension UUID, the command, the systemd unit, the apt package and the
  cache directory, so a 1.0.0 install is not upgraded in place by this: it is
  a separate install, and the old one is removed with its own `uninstall.sh`.
- The collector is one module per concern instead of one large file, with each
  agent's log format, quota endpoint and token handling behind a provider
  interface. Adding an agent is now one file plus a registry entry.
- The AppIndicator tray fallback is gone. The GNOME Shell extension draws the
  panel, and the terminal view covers everything else.
- The release number lives in a `VERSION` file, the only place it is written
  down. Both build scripts read it, so the `.deb` and the APT repository index
  cannot describe different versions of the same artifact.

### Added

- Preferences in the Extensions app, backed by a GSettings schema the
  collector reads too, so there is one store and nothing to keep in sync: how
  often quota is checked, which agents to show, the popup layout (tiles,
  compact or large numbers) and the panel style (ring or text).
- Token renewal on an explicit Refresh. Kimi is refreshed at `auth.kimi.com`
  under Kimi's own lock and never while a `kimi` process runs, with the result
  written back to its credentials file; Claude is left to renew its own, via
  `claude auth status` and at most one minimal `claude -p` prompt. The timed
  loop still never touches a token.
- An agent that is not installed is left out of the panel entirely, rather
  than drawn as an empty block.
- `tools/doctor.sh`, a read-only check that says why the panel indicator is
  not showing and gives the command for each thing it finds. It ships in the
  `.deb` as well, at `/usr/share/agent-usage/doctor.sh`, since a package
  install has no checkout to run it from.
- A test suite and CI: unittest on Python 3.8, 3.12 and 3.13, ruff,
  shellcheck, a JavaScript parse check, a schema compile check and a `.deb`
  build. The tests point every path the collector touches at a temporary
  directory, so they never read real tokens or logs.
- Documentation split out of the readme into `docs/packaging.md` and
  `docs/hacking.md`, plus a contributing guide, a security policy, a code of
  conduct, this changelog, issue and pull request templates, and an
  `.editorconfig`.

### Fixed

- The tray fallback called a function that did not exist, so it raised on its
  first draw. The tray is since gone, but the same mistake would have reached
  the panel.
- A cached quota reading outlived the window it measured. Once its reset time
  had passed the window had rolled over, yet the old percentage was still
  drawn as current, and the panel badge carried it with no last-known mark.
  Such rows are now dropped rather than zeroed, because what the new window
  holds is unknown until a fetch succeeds.
- The collector guarded its state write but not the quota calls above it, so
  an unexpected error ended the process and `Restart=always` respawned it
  every five seconds for as long as the cause lasted.
- Installing an update no longer needs a logout: the installer reloads the
  panel indicator itself, and waits for each step of the reload so an enable
  sent during a pending disable cannot be lost.
- The installer compared the running GNOME Shell against a version written
  into the script, and only complained when it was too old. A shell newer than
  the extension declares was installed over in silence, and the shell then
  refused to load the extension without saying why. The check now reads the
  range out of `metadata.json` and reports either side of it.
- The installer said nothing when `disable-user-extensions` was on. That one
  switch stops every user extension loading, with nothing in any log to
  explain the empty panel, which made a clean machine look like a broken
  install. It is now reported, with the command to turn extensions back on,
  and deliberately not flipped: that would also switch back on every other
  extension the user had turned off on purpose.

### Security

- A request carrying a token no longer follows redirects. `urllib` copies the
  `Authorization` header onto the redirected request, to any host and even
  from https down to plain http, so a redirect is now returned as an error.
- The cache directory is kept private to the user, and only the usage part of
  Kimi's reply is cached: the rest carries account and billing identifiers, so
  only its key names are kept.

## [1.0.0] - 2026-08-13

First release, under the name `ai-usage`.

### Added

- Claude Code and Kimi Code plan usage in the GNOME top bar: a ring gauge of
  the 5-hour window in the panel, and a popup with one bar per quota window,
  its reset time, and tokens spent today and over the last seven days, split
  by model.
- Percentages come from each provider's own usage API, never from an estimate
  over the logs. Token counts come from the local session logs, so they keep
  working when a quota endpoint does not.
- A terminal view, `ai-usage`, with the same reading, plus `--json`.
- A collector that runs as a systemd user service and writes one small JSON
  file. The GNOME Shell extension only reads and draws it, so the compositor
  never parses logs and never makes a network call.
- An AppIndicator tray fallback, `ai-usage --tray`, for sessions without the
  extension.
- A per-user installer, a `.deb` for system-wide installs, and a builder for a
  signed APT repository.

[1.0.0]: https://github.com/pgiahuy/agent-usage/releases/tag/v1.0.0
