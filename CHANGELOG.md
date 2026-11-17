# Changelog

Notable changes per release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- Preferences in the Extensions app: how often to check quota, which agents to
  show, the popup layout (tiles, compact or large numbers) and the panel style.
- Refresh renews an expired token, and a Claude token the server refuses
  before it expires. Kimi is refreshed under its own lock and never while
  `kimi` runs; Claude Code renews its own.
- Each agent's header shows how old its quota figures are.
- Agents that are not installed are left out.
- `tools/doctor.sh`, a read-only check of why the indicator is missing, also
  shipped in the `.deb`.

### Changed

- Renamed from `ai-usage` to `agent-usage`: the command, the extension UUID,
  the service, the package and the cache directory. A 1.0.0 install is not
  upgraded in place; remove it with its own `uninstall.sh`.
- Running `install.sh` again upgrades without a logout in most cases.
- Failure reasons are shorter: `connection refused`, not
  `[Errno 111] Connection refused`.

### Removed

- The AppIndicator tray, `--tray`. The extension and the terminal view cover it.

### Fixed

- The popup was close to unreadable under the shell's light style, the default
  on Ubuntu.
- Running `install.sh` again did not restart the collector, which kept running
  the old code until the next login.
- When quota could not be fetched, a window that had already reset kept its old
  percentage, unmarked in the panel.
- One log line of an unexpected shape stopped the panel updating for as long
  as the line stayed in the log.
- A log file replaced in place, at the same size or larger, lost its records.
- A malformed cached reading stopped the panel updating.
- A malformed state file left the popup empty until the next valid one.
- An unexpected error from a quota check crashed the collector, which then
  restarted every five seconds.
- The 429 backoff stayed at 60 seconds instead of doubling up to 15 minutes.
- Two rare deduplication gaps: a Kimi turn that differed from another only in
  cache writes was dropped, and a Claude record with no ids was counted again
  when its session was resumed.
- The installer did not warn when GNOME Shell was newer than the extension
  supports, or when user extensions were switched off.

### Security

- Requests carrying a token no longer follow redirects, which could send the
  token to another host.
- The cache directory is private to the user, and only the usage part of
  Kimi's reply is cached, without its account and billing identifiers.
- `build-apt-repo.sh` signs only with the key `AGENT_USAGE_GPG_KEY` names.
  1.0.0 fell back to the first secret key in the keyring and published its
  public half.

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

[Unreleased]: https://github.com/pgiahuy/agent-usage/compare/v1.0.0...HEAD
[1.0.0]: https://github.com/pgiahuy/agent-usage/releases/tag/v1.0.0
