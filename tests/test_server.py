import http.client
import json
import os
import socket
import subprocess
import sys
import time
import unittest

import _common

SERVER = os.path.join(_common.ROOT, "backend_api", "server.py")
JSON_HDR = {"Content-Type": "application/json"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith("BIBLIONX_LLM")}
        env.update(BIBLIONX_PORT=str(cls.port), BIBLIONX_HOST="127.0.0.1",
                   PYTHONIOENCODING="utf-8")
        cls.proc = subprocess.Popen([sys.executable, SERVER], env=env,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 30
        while time.time() < deadline:
            if cls.proc.poll() is not None:
                raise RuntimeError("server exited early")
            try:
                with socket.create_connection(("127.0.0.1", cls.port), timeout=0.5):
                    return
            except OSError:
                time.sleep(0.2)
        cls.proc.kill()
        raise RuntimeError("server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.proc.terminate()
        try:
            cls.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.proc.kill()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, dict(resp.getheaders()), resp.read()
        finally:
            conn.close()

    def post_text(self, text):
        return self.request("POST", "/api/v1/translate",
                            json.dumps({"texto": text}).encode("utf-8"), JSON_HDR)

    def test_health(self):
        status, _, body = self.request("GET", "/api/v1/health")
        self.assertEqual(status, 200)
        self.assertIsInstance(json.loads(body), dict)

    def test_translate(self):
        status, _, body = self.post_text("Ayer no fui a la casa")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertEqual(data["status"], "success")
        self.assertEqual(data["total_senas"], len(data["secuencia_senas"]))
        self.assertIn("secuencia_lsrd", data["nlp_analysis"])
        for key in ("es_deletreo", "match_method", "confidence"):
            self.assertIn(key, data["secuencia_senas"][0])

    def test_translate_validation(self):
        self.assertEqual(self.post_text("   ")[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/translate", b"not json", JSON_HDR)[0], 400)
        self.assertEqual(self.request("POST", "/api/v1/translate", b"[1]", JSON_HDR)[0], 400)

    def test_text_too_long_413(self):
        self.assertEqual(self.post_text("a " * 1500)[0], 413)

    def test_oversize_body_413(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        try:
            conn.putrequest("POST", "/api/v1/translate")
            conn.putheader("Content-Type", "application/json")
            conn.putheader("Content-Length", str(10 * 1024 * 1024))
            conn.endheaders()
            self.assertEqual(conn.getresponse().status, 413)
        finally:
            conn.close()

    def test_unknown_post_route_404(self):
        self.assertEqual(self.request("POST", "/api/v1/nope", b"{}")[0], 404)

    def test_static_app(self):
        status, headers, body = self.request("GET", "/app/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("Content-Type", ""))
        self.assertIn(b"<html", body.lower())
        status, headers, _ = self.request("GET", "/app/app.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("Content-Type", ""))

    def test_app_redirect(self):
        status, headers, _ = self.request("GET", "/app")
        self.assertIn(status, (301, 302, 307, 308))
        self.assertEqual(headers.get("Location"), "/app/")

    def test_traversal_blocked(self):
        paths = ("/app/../server.py", "/app/%2e%2e/server.py", "/app/..%2fserver.py",
                 "/app/%2e%2e%2f%2e%2e%2flsrd_dictionary.db", "/app/..%5cserver.py",
                 "/app/%00", "/extracted_images/../server.py",
                 "/extracted_images/%2e%2e/server.py")
        for path in paths:
            status, _, body = self.request("GET", path)
            self.assertNotEqual(status, 200, path)
            self.assertNotIn(b"LSRDApiHandler", body, path)

    def test_missing_static_404(self):
        self.assertEqual(self.request("GET", "/app/does-not-exist.js")[0], 404)

    def test_word_lookup_returns_json(self):
        status, _, body = self.request("GET", "/api/v1/words/abogado")
        self.assertIn(status, (200, 404))
        self.assertIsInstance(json.loads(body), dict)


if __name__ == "__main__":
    unittest.main()
