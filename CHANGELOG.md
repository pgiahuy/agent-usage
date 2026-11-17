# Changelog

Notable changes per release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Changed

- Renamed from `ai-usage` to `agent-usage`: the command, the extension UUID,
  the service, the package and the cache directory. A 1.0.0 install is not
  upgraded in place; remove it with its own `uninstall.sh`.
- Running `install.sh` again upgrades without a logout in most cases.
- The AppIndicator tray (`--tray`) is gone. The extension and the terminal
  view cover it.
- The collector is split into modules, with one provider module per agent.

### Added

- Preferences in the Extensions app: how often to check quota, which agents to
  show, the popup layout (tiles, compact or large numbers) and the panel style.
- Refresh renews an expired token, and a Claude token the server refuses
  before it expires. Kimi is refreshed under its own lock and never while
  `kimi` runs; Claude Code renews its own. The timed loop never touches a
  token.
- Each agent's header shows how old its quota figures are.
- Agents that are not installed are left out.
- `tools/doctor.sh`, a read-only check of why the indicator is missing, also
  shipped in the `.deb`.
- Tests and CI, a contributing guide, a security policy, a code of conduct, and
  issue and pull request templates.

### Fixed

- The popup was close to unreadable under the shell's light style, the default
  on Ubuntu.
- A usage window that had already reset kept showing its old percentage as
  current.
- On Python 3.8 to 3.10, a reset time ending in `Z` was not parsed: no reset
  time was shown, and a window that had reset kept its old percentage.
- One unreadable line in a session log stopped the panel updating for as long
  as the line stayed in the log.
- A log file replaced in place, at the same size or larger, lost its records.
- A malformed cached reading stopped the panel updating.
- A malformed state file broke the popup until the extension was restarted.
- An unexpected error from a quota check crashed the collector, which then
  restarted every five seconds.
- The 429 backoff stayed at 60 seconds instead of doubling up to 15 minutes.
- Two rare deduplication gaps: a Kimi turn that differed from another only in
  cache writes was dropped, and a Claude record with no ids was counted again
  when its session was resumed.
- Failure reasons are shorter: `connection refused`, not
  `[Errno 111] Connection refused`.
- The installer did not warn when GNOME Shell was newer than the extension
  supports, or when user extensions were switched off.

### Security

- Requests carrying a token no longer follow redirects, which could send the
  token to another host.
- The cache directory is private to the user, and only the usage part of
  Kimi's reply is cached, without its account and billing identifiers.

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
