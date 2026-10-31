# Security

## Reporting a vulnerability

Please report privately, not in a public issue.

Use GitHub's private vulnerability reporting on this repository: open the
**Security** tab and choose **Report a vulnerability**. That opens a thread
only you and the maintainers can read.

Tell us what you found, how to reproduce it, and what an attacker gets out of
it. A proof of concept helps but is not required to file. Expect a first reply
within a week. If a report turns out to be valid, the fix and the advisory go
out together, and you are credited unless you ask otherwise.

This is a small project maintained in spare time. There is no bounty.

## Supported versions

Only the latest release and the `main` branch get fixes. There are no
maintenance branches for older versions.

## What this tool touches

The collector runs as your own user, with no elevated privileges, and is worth
reviewing with that in mind. It:

- **reads access tokens** from `~/.claude/.credentials.json` and
  `~/.kimi-code/credentials/kimi-code.json`, the files Claude Code and Kimi
  Code write when you sign in;
- **reads session logs** under `~/.claude/projects/` and
  `~/.kimi-code/sessions/`, which contain your prompts and the models' replies;
- **sends a bearer token** to `api.anthropic.com`, `api.kimi.com` and, only on
  an explicit Refresh, `auth.kimi.com`;
- **writes** inside `~/.cache/agent-usage` and, on an explicit Kimi Refresh,
  back to Kimi's own credentials file;
- **runs** `claude auth status` and at most one minimal `claude -p` prompt, on
  an explicit Refresh, so Claude Code renews its own token.

It sends nothing anywhere else and collects no telemetry.

## Deliberate defences

These are not incidental, so a change that removes one needs a reason:

- **No redirects on an authenticated request.** `urllib` copies the
  `Authorization` header onto a redirected request, to any host and even from
  https down to plain http. `daemon/net.py` turns every redirect into an error
  instead of following it.
- **The cache directory is kept at mode 0700**, because it holds quota
  readings and the raw provider replies.
- **Kimi's credentials file is rewritten at mode 0600**, atomically, and only
  under the same lock Kimi Code itself uses, never while a `kimi` process is
  running. Kimi rotates its refresh token, so two refreshes racing would leave
  one side holding a dead token and sign the user out.
- **The timed loop never touches a token.** Only the Refresh button renews an
  expired one, so nothing rotates behind your back.
- **The OAuth host must be https.** A plain-http token endpoint is refused.
- **Only the usage part of Kimi's reply is cached.** The rest carries account
  and billing identifiers, so only its key names are kept.
- **The GNOME Shell extension makes no network calls and parses no logs.** It
  reads one small JSON file written by the collector. Keeping work out of the
  compositor is the reason the split exists.

## Out of scope

- Anything that needs an attacker to already have read access to your home
  directory. At that point your tokens are readable with or without this tool.
- The quota endpoints themselves. `api.anthropic.com/api/oauth/usage` is
  undocumented and `api.kimi.com` is discovered by probing, so either can
  change or stop answering. That breaks the readout; it is not a vulnerability
  here.
- Numbers that look wrong. Please file those as ordinary bugs.
