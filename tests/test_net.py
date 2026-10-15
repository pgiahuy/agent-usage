import _env  # noqa: F401  (must come first)

import threading
import unittest
import urllib.error
from http.server import BaseHTTPRequestHandler, HTTPServer

import net


def serve(handler):
    server = HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


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
