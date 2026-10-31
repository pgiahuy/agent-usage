# Changelog

Notable changes per release. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

## Unreleased

### Added

- A `VERSION` file as the only place the release number is written down. The
  `.deb` build and the APT repository build both read it, so they can no
  longer disagree with each other or with the tag.
- `version-name` in the extension metadata, so GNOME shows a readable version
  beside the integer it requires.
- Contributing guide, security policy, code of conduct, this changelog, issue
  and pull request templates, and an `.editorconfig`.
- `tools/doctor.sh`, a read-only check that says why the panel indicator is
  not showing and gives the command for each thing it finds. It ships inside
  the `.deb` too, at `/usr/share/agent-usage/doctor.sh`, since a package
  install has no checkout to run it from.

### Fixed

- The installer compared the running GNOME Shell against a version written
  into the script, and only complained when it was too old. A shell newer than
  the extension declares was installed over in silence, and the shell then
  refused to load the extension without saying why. The check now reads the
  range out of `metadata.json`, so it cannot drift, and reports either side of
  it.
- The installer said nothing when `disable-user-extensions` was on. That one
  switch stops every user extension loading, with nothing in any log to
  explain the empty panel, which made a fresh machine look like a broken
  install. It is now reported, with the command to turn extensions back on,
  and deliberately not flipped: doing that would also switch back on every
  other extension the user had turned off on purpose.

## [1.0.0] - 2026-08-13

First release.

### Added

- Claude Code and Kimi Code plan usage in the GNOME top bar: a ring or text in
  the panel, and a popup with one bar per quota window, its reset time, and
  tokens spent today and over the last seven days, split by model.
- Percentages come from each provider's own usage API, never from an estimate
  over the logs. Token counts come from the local session logs, so they keep
  working when a quota endpoint does not.
- A terminal view, `agent-usage`, with the same reading, plus `--json`.
- A collector that runs as a systemd user service and writes one small JSON
  file. The GNOME Shell extension only reads and draws it, so the compositor
  never parses logs and never makes a network call.
- Preferences in the Extensions app: how often quota is checked, which agents
  to show, the popup layout and the panel style.
- A per-user installer, a `.deb` for system-wide installs, and a builder for a
  signed APT repository.
- Token renewal on an explicit Refresh only: Kimi under its own lock and never
  while `kimi` runs, Claude by letting Claude Code renew its own.

[1.0.0]: https://github.com/pgiahuy/agent-usage/releases/tag/v1.0.0
