"""Server hardening tests: rate limit, CORS, CSP, image fallback, metrics, logs."""
import http.client
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest

try:
    import _common
except ModuleNotFoundError:
    from tests import _common

SERVER = os.path.join(_common.ROOT, "backend_api", "server.py")
JSON_HDR = {"Content-Type": "application/json"}


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class ServerCase(unittest.TestCase):
    ENV = {}

    @classmethod
    def setUpClass(cls):
        cls.port = free_port()
        env = {k: v for k, v in os.environ.items() if not k.startswith("BIBLIONX_")}
        env.update(BIBLIONX_PORT=str(cls.port), BIBLIONX_HOST="127.0.0.1",
                   PYTHONIOENCODING="utf-8")
        env.update(cls.ENV)
        cls.logfile = tempfile.TemporaryFile()
        cls.proc = subprocess.Popen([sys.executable, SERVER], env=env,
                                    stdout=cls.logfile, stderr=subprocess.DEVNULL)
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
        cls.logfile.close()

    def request(self, method, path, body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=15)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            return resp.status, {k.lower(): v for k, v in resp.getheaders()}, resp.read()
        finally:
            conn.close()

    def post_text(self, text, headers=None):
        h = dict(JSON_HDR)
        h.update(headers or {})
        return self.request("POST", "/api/v1/translate",
                            json.dumps({"texto": text}).encode("utf-8"), h)


class DefaultsTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "0"}

    def test_no_cors_header_by_default(self):
        _, headers, _ = self.request("GET", "/api/v1/health",
                                     headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", headers)
        status, headers, _ = self.request("OPTIONS", "/api/v1/translate",
                                          headers={"Origin": "https://evil.example"})
        self.assertEqual(status, 204)
        self.assertNotIn("access-control-allow-origin", headers)

    def test_security_headers_everywhere(self):
        for path in ("/api/v1/health", "/app/", "/nope"):
            _, headers, _ = self.request("GET", path)
            self.assertEqual(headers.get("x-content-type-options"), "nosniff", path)
            self.assertEqual(headers.get("referrer-policy"), "no-referrer", path)
            self.assertEqual(headers.get("x-frame-options"), "DENY", path)
            self.assertTrue(headers.get("x-request-id"), path)

    def test_csp_on_app_only(self):
        _, headers, _ = self.request("GET", "/app/")
        csp = headers.get("content-security-policy", "")
        for part in ("default-src 'self'", "img-src 'self' data:", "script-src 'self'",
                     "style-src 'self'", "connect-src 'self'", "font-src 'self'",
                     "frame-ancestors 'none'"):
            self.assertIn(part, csp)
        _, headers, _ = self.request("GET", "/api/v1/health")
        self.assertNotIn("content-security-policy", headers)

    def test_metrics_on_for_localhost(self):
        self.post_text("hola")
        status, _, body = self.request("GET", "/api/v1/metrics")
        self.assertEqual(status, 200)
        data = json.loads(body)
        self.assertGreaterEqual(data["translate_count"], 1)
        self.assertIn("requests_by_status", data)
        self.assertIn("match_method_counts", data)
        self.assertIn("uptime_seconds", data)

    def test_structured_logs_without_text(self):
        marker = "palabrasecretaunica"
        self.post_text(marker)
        time.sleep(0.3)
        self.logfile.seek(0)
        out = self.logfile.read().decode("utf-8", "replace")
        self.assertNotIn(marker, out)
        lines = [json.loads(ln) for ln in out.splitlines() if ln.startswith("{")]
        self.assertTrue(lines)
        for key in ("ts", "request_id", "method", "path", "status", "ms", "client"):
            self.assertIn(key, lines[-1])
        self.assertNotIn("127.0.0.1", lines[-1]["client"])


class MissingImagesTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "0"}

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.ENV = dict(cls.ENV, BIBLIONX_IMAGES_DIR=cls.tmp.name)
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls.tmp.cleanup()

    def test_missing_image_flagged(self):
        status, _, body = self.post_text("Ayer fui a la casa con mi madre")
        self.assertEqual(status, 200)
        signs = json.loads(body)["secuencia_senas"]
        self.assertTrue(signs)
        for sign in signs:
            self.assertIs(sign["image_available"], False)
            self.assertNotIn("url_imagen", sign)

    def test_image_route_404(self):
        self.assertEqual(self.request("GET", "/extracted_images/1.png")[0], 404)


class ImagePresentTests(ServerCase):
    """Uses a tiny committed fixture, so it always runs (no local images needed)."""
    FIXTURES = os.path.join(_common.ROOT, "tests", "fixtures", "images")
    ENV = {"BIBLIONX_RATE_PER_MIN": "0", "BIBLIONX_IMAGES_DIR": FIXTURES}

    def test_present_image_gets_url(self):
        self.assertTrue(os.path.isfile(os.path.join(self.FIXTURES, "lsrd_0001.png")))
        # "a" alone is now a dropped preposition; a fingerspelled name starting
        # with A still yields the letter sign lsrd_0001.
        _, _, body = self.post_text("Ana")
        signs = [s for s in json.loads(body)["secuencia_senas"]
                 if str(s.get("ruta_imagen", "")).endswith("lsrd_0001.png")]
        self.assertTrue(signs, "expected the sign for 'A' (lsrd_0001)")
        for sign in signs:
            self.assertIs(sign["image_available"], True)
            self.assertIn("/extracted_images/lsrd_0001.png", sign["url_imagen"])
        status, headers, _ = self.request("GET", "/extracted_images/lsrd_0001.png")
        self.assertEqual(status, 200)


class CorsConfiguredTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "0",
           "BIBLIONX_CORS_ORIGIN": "https://a.example, https://b.example"}

    def test_matching_origin_echoed(self):
        _, headers, _ = self.request("GET", "/api/v1/health",
                                     headers={"Origin": "https://b.example"})
        self.assertEqual(headers.get("access-control-allow-origin"), "https://b.example")
        self.assertIn("Origin", headers.get("vary", ""))

    def test_other_origin_rejected(self):
        _, headers, _ = self.request("GET", "/api/v1/health",
                                     headers={"Origin": "https://evil.example"})
        self.assertNotIn("access-control-allow-origin", headers)


class CorsWildcardTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "0", "BIBLIONX_CORS_ORIGIN": "*"}

    def test_wildcard(self):
        _, headers, _ = self.request("GET", "/api/v1/health",
                                     headers={"Origin": "https://x.example"})
        self.assertEqual(headers.get("access-control-allow-origin"), "*")


class RateLimitTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "3"}

    def test_xff_ignored_and_429_with_retry_after(self):
        results = [self.request("GET", "/api/v1/words/casa",
                                headers={"X-Forwarded-For": "10.0.0.%d" % i})
                   for i in range(8)]
        limited = [r for r in results if r[0] == 429]
        self.assertTrue(limited)
        status, headers, body = limited[0]
        self.assertGreaterEqual(int(headers["retry-after"]), 1)
        self.assertEqual(json.loads(body)["status"], "error")
        # health is not rate limited
        self.assertEqual(self.request("GET", "/api/v1/health")[0], 200)


class RateLimitTrustProxyTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "2", "BIBLIONX_TRUST_PROXY": "1"}

    def test_per_forwarded_client_buckets(self):
        def get(ip):
            return self.request("GET", "/api/v1/words/casa",
                                headers={"X-Forwarded-For": ip})[0]
        self.assertNotEqual(get("1.1.1.1"), 429)
        self.assertNotEqual(get("1.1.1.1"), 429)
        self.assertEqual(get("1.1.1.1"), 429)
        self.assertNotEqual(get("2.2.2.2"), 429)


class MetricsDisabledTests(ServerCase):
    ENV = {"BIBLIONX_RATE_PER_MIN": "0", "BIBLIONX_METRICS": "0"}

    def test_metrics_404(self):
        self.assertEqual(self.request("GET", "/api/v1/metrics")[0], 404)


if __name__ == "__main__":
    unittest.main()
