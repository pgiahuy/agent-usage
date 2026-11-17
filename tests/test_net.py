import _env  # noqa: F401  (must come first)

import socket
import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import net


def serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


class WhyTest(unittest.TestCase):
    """The reason shown in a panel row: short, and never a path on this disk."""

    HOME_FILE = "/home/someone/.kimi-code/credentials/kimi-code.json"

    def test_a_failed_file_operation_gives_the_reason_not_the_path(self):
        for exc in (FileNotFoundError(2, "No such file or directory", self.HOME_FILE),
                    PermissionError(13, "Permission denied", self.HOME_FILE),
                    OSError(28, "No space left on device", self.HOME_FILE)):
            text = net.why(exc)
            self.assertNotIn("/", text, text)
            self.assertNotIn("someone", text, text)
        self.assertEqual(net.why(FileNotFoundError(2, "No such file or directory",
                                                   self.HOME_FILE)),
                         "no such file or directory")

    def test_a_wrapped_socket_error_gives_the_reason(self):
        exc = urllib.error.URLError(ConnectionRefusedError(111, "Connection refused"))
        self.assertEqual(net.why(exc), "connection refused")

    def test_no_network_and_timeouts_keep_their_short_names(self):
        self.assertEqual(net.why(urllib.error.URLError(socket.gaierror(-3, "x"))), "no network")
        self.assertEqual(net.why(socket.gaierror(-3, "x")), "no network")
        self.assertEqual(net.why(urllib.error.URLError(TimeoutError())), "timed out")
        self.assertEqual(net.why(TimeoutError()), "timed out")

    def test_an_error_that_is_not_about_a_file_keeps_its_message(self):
        # A JSON error says what was wrong with the reply, and has no path in it.
        self.assertEqual(net.why(ValueError("Expecting value: line 1 column 1 (char 0)")),
                         "Expecting value: line 1 column 1 (char 0)")
        self.assertEqual(net.why(urllib.error.URLError("unknown url type: ftp")),
                         "unknown url type: ftp")

    def test_an_oserror_with_no_errno_still_names_something(self):
        self.assertEqual(net.why(OSError()), "OSError")
        self.assertEqual(net.why(PermissionError()), "PermissionError")


class RedirectTest(unittest.TestCase):
    """A bearer token must never follow a redirect to another origin."""

    @classmethod
    def setUpClass(cls):
        cls.seen = []

        class Elsewhere(BaseHTTPRequestHandler):
            def do_GET(self):
                cls.seen.append(self.headers.get("Authorization"))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"{}")

            def log_message(self, *args):
                pass

        cls.elsewhere = serve(Elsewhere)

        class Redirect(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(302)
                self.send_header("Location", "http://localhost:%d/" % cls.elsewhere.server_port)
                self.end_headers()

            do_POST = do_GET

            def log_message(self, *args):
                pass

        cls.redirect = serve(Redirect)

    @classmethod
    def tearDownClass(cls):
        for server in (cls.elsewhere, cls.redirect):
            server.shutdown()
            server.server_close()

    def test_get_with_token(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            net.get_json("http://127.0.0.1:%d/" % self.redirect.server_port, "SECRET", 5)
        net.discard(ctx.exception)
        self.assertEqual(ctx.exception.code, 302)
        self.assertEqual(self.seen, [])

    def test_post_form(self):
        with self.assertRaises(urllib.error.HTTPError) as ctx:
            net.post_form("http://127.0.0.1:%d/" % self.redirect.server_port,
                          {"refresh_token": "SECRET"}, 5)
        net.discard(ctx.exception)
        self.assertEqual(self.seen, [])


if __name__ == "__main__":
    unittest.main()
