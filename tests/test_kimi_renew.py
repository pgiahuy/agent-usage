import _env  # noqa: F401  (must come first)

import json
import os
import threading
import time
import unittest
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

import net
from providers import kimi


class FakeAuth(BaseHTTPRequestHandler):
    status = 200
    requests = []

    def do_POST(self):
        length = int(self.headers["Content-Length"])
        FakeAuth.requests.append((self.path, self.headers.get("Content-Type"),
                                  urllib.parse.parse_qs(self.rfile.read(length).decode())))
        self.send_response(FakeAuth.status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        if FakeAuth.status == 200:
            self.wfile.write(json.dumps({"access_token": "NEW_AT", "refresh_token": "NEW_RT",
                                         "expires_in": 900}).encode())
        else:
            self.wfile.write(b'{"error": "invalid_grant"}')

    def log_message(self, *args):
        pass


class Route:
    """The refresh insists on https; send its https URL to the local http server."""

    def __init__(self, port):
        self.port = port
        self.real = net.OPENER

    def open(self, req, timeout=None):
        local = "http://127.0.0.1:%d" % self.port
        req.full_url = req.full_url.replace("https://auth.example", local)
        return self.real.open(req, timeout=timeout)


class RenewTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = HTTPServer(("127.0.0.1", 0), FakeAuth)
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        FakeAuth.status, FakeAuth.requests = 200, []
        os.makedirs(os.path.dirname(kimi.CREDS), exist_ok=True)
        with open(kimi.CREDS, "w") as fh:
            json.dump({"access_token": "OLD", "refresh_token": "OLD_RT",
                       "expires_at": int(time.time()) - 100, "scope": "kimi-code"}, fh)
        self.saved = (kimi.OAUTH_HOST, kimi._kimi_running, net.OPENER)
        kimi.OAUTH_HOST = "https://auth.example"
        kimi._kimi_running = lambda: False
        net.OPENER = Route(self.server.server_port)

    def tearDown(self):
        kimi.OAUTH_HOST, kimi._kimi_running, net.OPENER = self.saved
        if os.path.isdir(kimi.REFRESH_LOCK):
            os.rmdir(kimi.REFRESH_LOCK)

    def creds(self):
        with open(kimi.CREDS) as fh:
            return json.load(fh)

    def test_refresh_rotates_and_writes_back(self):
        self.assertIsNone(kimi.renew())
        path, ctype, body = FakeAuth.requests[0]
        self.assertEqual((path, ctype), ("/api/oauth/token", "application/x-www-form-urlencoded"))
        self.assertEqual(body, {"client_id": [kimi.CLIENT_ID], "grant_type": ["refresh_token"],
                                "refresh_token": ["OLD_RT"]})
        creds = self.creds()
        self.assertEqual((creds["access_token"], creds["refresh_token"]), ("NEW_AT", "NEW_RT"))
        self.assertEqual(creds["scope"], "kimi-code")  # fields kimi wrote are kept
        self.assertEqual(os.stat(kimi.CREDS).st_mode & 0o777, 0o600)
        self.assertFalse(os.path.exists(kimi.REFRESH_LOCK))

    def test_mode_holds_even_with_residue_at_the_temp_path(self):
        """O_CREAT's mode is ignored when the file already exists.

        A crashed earlier run can leave the temp file behind, and it used to
        keep whatever mode it had: the fresh refresh token then landed in a
        world-readable file.
        """
        tmp = kimi.CREDS + ".agent-usage.tmp"
        with open(tmp, "w") as fh:
            fh.write("residue")
        os.chmod(tmp, 0o666)
        self.assertIsNone(kimi.renew())
        self.assertEqual(os.stat(kimi.CREDS).st_mode & 0o777, 0o600)
        self.assertEqual(self.creds()["access_token"], "NEW_AT")
        self.assertFalse(os.path.exists(tmp))

    def test_a_symlink_at_the_temp_path_is_not_followed(self):
        """open() follows symlinks, so the token could be written through one."""
        tmp = kimi.CREDS + ".agent-usage.tmp"
        victim = os.path.join(os.path.dirname(kimi.CREDS), "victim")
        with open(victim, "w"):
            pass
        os.symlink(victim, tmp)
        self.assertIsNone(kimi.renew())
        with open(victim) as fh:
            self.assertEqual(fh.read(), "")  # nothing went through the link
        self.assertEqual(self.creds()["access_token"], "NEW_AT")

    def test_valid_token_sends_nothing(self):
        kimi.renew()
        FakeAuth.requests = []
        self.assertIsNone(kimi.renew())
        self.assertEqual(FakeAuth.requests, [])

    def test_lock_held_by_kimi(self):
        os.makedirs(kimi.REFRESH_LOCK)
        self.assertEqual(kimi.renew(), "kimi is refreshing")
        self.assertEqual(FakeAuth.requests, [])
        self.assertTrue(os.path.isdir(kimi.REFRESH_LOCK))  # kimi's lock, left alone

    def test_kimi_running(self):
        kimi._kimi_running = lambda: True
        self.assertEqual(kimi.renew(), "kimi is running")
        self.assertEqual(FakeAuth.requests, [])

    def test_rejected_leaves_the_file(self):
        FakeAuth.status = 400
        self.assertEqual(kimi.renew(), "refresh HTTP 400")
        self.assertEqual(self.creds()["refresh_token"], "OLD_RT")
        self.assertFalse(os.path.exists(kimi.REFRESH_LOCK))

    def test_plain_http_host_refused(self):
        kimi.OAUTH_HOST = "http://auth.example"
        self.assertEqual(kimi.renew(), "oauth host is not https")
        self.assertEqual(FakeAuth.requests, [])


if __name__ == "__main__":
    unittest.main()
