# Security

## Reporting a vulnerability

Report privately, not in a public issue: on this repository's **Security** tab,
choose **Report a vulnerability**. Only you and the maintainers can read the
thread.

Include what you found, how to reproduce it, and what an attacker gains. A proof
of concept helps but is not required. Expect a first reply within a week. A
valid report gets its fix and advisory published together, with credit to you
unless you ask otherwise.

This is a small project maintained in spare time. There is no bounty.

## Supported versions

Only the latest release and the `main` branch receive fixes.

## What the collector touches

The collector runs as your user, with no elevated privileges. It:

- **reads access tokens** from `~/.claude/.credentials.json` and
  `~/.kimi-code/credentials/kimi-code.json`, written by Claude Code and Kimi
  Code when you sign in;
- **reads session logs** under `~/.claude/projects/` and
  `~/.kimi-code/sessions/`, which contain your prompts and the models' replies;
- **sends the access token** as a bearer header to `api.anthropic.com` and
  `api.kimi.com`, and on an explicit Refresh **posts Kimi's refresh token** to
  `auth.kimi.com`, or to the https host `KIMI_CODE_OAUTH_HOST` names;
- **writes** inside `~/.cache/agent-usage`, and on an explicit Kimi refresh,
  Kimi's credentials file, a temporary file beside it, and Kimi's lock
  directory `~/.kimi-code/oauth/kimi-code.lock`;
- **reads** `/proc/*/cmdline` and `/proc/*/exe` on a Kimi refresh, to check
  that no `kimi` process is running;
- **runs** `gsettings get` for its settings on every pass, and on an explicit
  Refresh, only when Claude's token is expired or refused, `claude auth status`
  and at most one minimal `claude -p` prompt per renewal, so that Claude Code
  renews its own token.

It sends nothing anywhere else and collects no telemetry.

## Deliberate defences

A change that removes one of these needs a stated reason:

- **No redirects on authenticated requests.** `urllib` would copy the
  `Authorization` header to any redirect target, even plain http.
  `daemon/net.py` treats a redirect as an error.
- **The cache directory is mode 0700.** It holds quota readings and provider
  replies.
- **Kimi's credentials file is written atomically at mode 0600**, only under
  the lock Kimi Code itself uses, and never while a `kimi` process runs. Kimi
  rotates its refresh token, so two refreshes racing would sign the user out.
- **The timed loop never renews a token.** Only Refresh does: a token that has
  expired, or a Claude token the server has refused.
- **The OAuth host must be https.**
- **Only the usage part of Kimi's reply is cached.** The rest carries account
  and billing identifiers, so only its key names are kept.
- **The GNOME Shell extension makes no network calls and parses no logs.** It
  reads `state.json`, the ring icons and its settings, and writes one empty
  file to ask the collector for a refresh.

## Out of scope

- Attacks that need read access to your home directory. With that, your tokens
  are readable with or without this tool.
- The quota endpoints themselves. Anthropic's is undocumented and Kimi's is
  found by probing, so either may change or stop answering. That breaks the
  readout but is not a vulnerability here.
- Numbers that look wrong. File those as ordinary bugs.
