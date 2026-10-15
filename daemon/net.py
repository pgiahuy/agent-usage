"""HTTP for the quota and token endpoints: JSON in, JSON out, no redirects."""
from __future__ import annotations

import json
import socket
import urllib.error
import urllib.parse
import urllib.request

USER_AGENT = "agent-usage-indicator/1.0"


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """Turn every redirect into an HTTPError instead of following it.

    urllib copies the Authorization header onto the redirected request, to any
    host and even from https down to http, so following one would hand the
    bearer token to wherever the Location points.
    """

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = urllib.request.build_opener(_NoRedirect)


def get_json(url, token, timeout, extra_headers=None):
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
    }
    if extra_headers:
        headers.update(extra_headers)
    req = urllib.request.Request(url, headers=headers)
    with OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def post_form(url, fields, timeout):
    req = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(fields).encode(),
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "User-Agent": USER_AGENT,
        },
    )
    with OPENER.open(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def discard(exc):
    """Release the response an HTTPError holds; the daemon runs for days. One
    built without a response (fp=None) has nothing to release, and before
    Python 3.9 its close() fails."""
    if getattr(exc, "fp", None) is not None:
        exc.close()


def why(exc):
    """A short reason a request failed, fit for a narrow panel row.

    urllib wraps everything as '<urlopen error [Errno -3] Temporary failure in
    name resolution>', which says little and does not fit anywhere.
    """
    if isinstance(exc, urllib.error.URLError):
        reason = getattr(exc, "reason", None)
        if isinstance(reason, socket.gaierror):
            return "no network"
        if isinstance(reason, TimeoutError):
            return "timed out"
        if reason is not None:
            return str(reason)
    if isinstance(exc, TimeoutError):
        return "timed out"
    return str(exc)
