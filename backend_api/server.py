#!/usr/bin/env python3
"""
HTTP REST API server for the Dominican Sign Language (LSRD) translator.
Built on Python's http.server (standard library only).

Endpoints:
  - POST /api/v1/translate      -> {"texto": "..."}
  - GET  /api/v1/words/{lemma}
  - GET  /api/v1/health
  - GET  /api/v1/metrics        (only when BIBLIONX_METRICS is enabled)
  - GET  /extracted_images/{filename}
  - GET  /app/ and /app/{file}  -> static web UI from backend_api/web/

The translation modules and the SQLite dictionary live in the repository
root; this server imports them from there (no copies).

Environment variables:
  - BIBLIONX_HOST          bind address (default 127.0.0.1)
  - BIBLIONX_PORT          bind port (default 8000)
  - BIBLIONX_IMAGES_DIR    sign images directory (default <repo root>/extracted_images).
                           Missing files are tolerated: signs get image_available=false.
  - BIBLIONX_CORS_ORIGIN   comma-separated allowed origins, or '*'. Default: unset,
                           i.e. same-origin only (no CORS headers).
  - BIBLIONX_RATE_PER_MIN  per-IP requests/minute for translate and words (default 120, 0 = off)
  - BIBLIONX_TRUST_PROXY   '1' to take the client IP from X-Forwarded-For (default off)
  - BIBLIONX_METRICS       '1'/'0' to enable/disable GET /api/v1/metrics
                           (default: on only when bound to localhost)
"""

import os
import re
import sys
import json
import time
import uuid
import hashlib
import threading
import mimetypes
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(BASE_DIR)
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from nlp_engine import LSRDNlpEngine  # noqa: E402
from translator import LSRDTranslator  # noqa: E402

VERSION = "1.2.0"
HOST = os.environ.get("BIBLIONX_HOST", "127.0.0.1")


def _env_int(name, default):
    try:
        return max(0, int(os.environ.get(name, str(default))))
    except ValueError:
        return default


PORT = _env_int("BIBLIONX_PORT", 8000) or 8000
CORS_RAW = os.environ.get("BIBLIONX_CORS_ORIGIN", "").strip()
CORS_ALL = CORS_RAW == "*"
CORS_ORIGINS = frozenset(o.strip().rstrip("/") for o in CORS_RAW.split(",")
                         if o.strip() and o.strip() != "*")
RATE_PER_MIN = _env_int("BIBLIONX_RATE_PER_MIN", 120)
TRUST_PROXY = os.environ.get("BIBLIONX_TRUST_PROXY", "") == "1"
_LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
_metrics_env = os.environ.get("BIBLIONX_METRICS")
METRICS_ENABLED = (_metrics_env == "1") if _metrics_env in ("0", "1") else HOST in _LOCAL_HOSTS

MAX_BODY_BYTES = 64 * 1024
MAX_TEXT_CHARS = 2000

IMAGES_DIR = os.path.abspath(os.environ.get("BIBLIONX_IMAGES_DIR")
                             or os.path.join(ROOT_DIR, "extracted_images"))
WEB_DIR = os.path.join(BASE_DIR, "web")

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
       "connect-src 'self'; font-src 'self'; frame-ancestors 'none'")

MIME_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".mjs": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".ico": "image/x-icon",
    ".woff2": "font/woff2",
    ".txt": "text/plain; charset=utf-8",
}

_HOST_RE = re.compile(r"^[A-Za-z0-9.\-]+(:\d{1,5})?$|^\[[0-9A-Fa-f:.]+\](:\d{1,5})?$")

nlp_engine = LSRDNlpEngine()
translator = LSRDTranslator()


def safe_join(root, relative):
    """Resolve `relative` under `root`; return None on traversal attempts."""
    if "\x00" in relative or "\\" in relative:
        return None
    root_real = os.path.realpath(root)
    candidate = os.path.realpath(os.path.join(root_real, relative))
    if candidate != root_real and not candidate.startswith(root_real + os.sep):
        return None
    return candidate


class RateLimiter:
    """Per-key token bucket: capacity == rate per minute, refilled continuously."""

    def __init__(self, per_min):
        self.per_min = per_min
        self._buckets = {}
        self._lock = threading.Lock()

    def check(self, key):
        """Return 0.0 if allowed, else seconds to wait before retrying."""
        if self.per_min <= 0:
            return 0.0
        now = time.monotonic()
        rate = self.per_min / 60.0
        with self._lock:
            tokens, last = self._buckets.get(key, (float(self.per_min), now))
            tokens = min(float(self.per_min), tokens + (now - last) * rate)
            if tokens >= 1.0:
                self._buckets[key] = (tokens - 1.0, now)
                if len(self._buckets) > 10000:
                    self._buckets = {k: v for k, v in self._buckets.items()
                                     if now - v[1] < 120}
                return 0.0
            self._buckets[key] = (tokens, now)
            return (1.0 - tokens) / rate


class Metrics:
    def __init__(self):
        self.started = time.time()
        self.requests_total = 0
        self.by_status = {}
        self.translate_count = 0
        self.translate_ms_total = 0.0
        self.match_methods = {}
        self._lock = threading.Lock()

    def record(self, status, ms, is_translate):
        with self._lock:
            self.requests_total += 1
            self.by_status[str(status)] = self.by_status.get(str(status), 0) + 1
            if is_translate and status == 200:
                self.translate_count += 1
                self.translate_ms_total += ms

    def record_methods(self, signs):
        with self._lock:
            for sign in signs:
                m = str(sign.get("match_method") or "unknown")
                self.match_methods[m] = self.match_methods.get(m, 0) + 1

    def snapshot(self):
        with self._lock:
            n = self.translate_count
            return {
                "uptime_seconds": round(time.time() - self.started, 1),
                "requests_total": self.requests_total,
                "requests_by_status": dict(self.by_status),
                "translate_count": n,
                "translate_avg_ms": round(self.translate_ms_total / n, 2) if n else 0.0,
                "match_method_counts": dict(self.match_methods),
            }


rate_limiter = RateLimiter(RATE_PER_MIN)
metrics = Metrics()
_LOG_SALT = uuid.uuid4().hex


def image_exists(ruta):
    name = os.path.basename(str(ruta or "").replace("\\", "/"))
    if not name:
        return False
    target = safe_join(IMAGES_DIR, name)
    return bool(target) and os.path.isfile(target)


class LSRDApiHandler(BaseHTTPRequestHandler):
    server_version = "BiblionxAPI/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---------- helpers ----------
    def _cors_headers(self):
        """CORS is opt-in: no header at all unless configured (same-origin default)."""
        origin = (self.headers.get("Origin") or "").strip().rstrip("/")
        if CORS_ALL:
            self.send_header("Access-Control-Allow-Origin", "*")
        elif origin and origin in CORS_ORIGINS:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        else:
            if CORS_ORIGINS:
                self.send_header("Vary", "Origin")
            return
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")

    def send_response(self, code, message=None):
        self._status = code
        super().send_response(code, message)

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Request-Id", getattr(self, "_rid", "-"))
        if self.path.split("?", 1)[0].startswith("/app"):
            self.send_header("Content-Security-Policy", CSP)
        self._cors_headers()
        super().end_headers()

    def _client_ip(self):
        if TRUST_PROXY:
            xff = (self.headers.get("X-Forwarded-For") or "").split(",")
            last = xff[-1].strip() if xff else ""
            if last:
                return last
        return self.client_address[0]

    def _client_hash(self):
        return hashlib.sha256((_LOG_SALT + self._client_ip()).encode()).hexdigest()[:12]

    def _rate_limited(self):
        wait = rate_limiter.check(self._client_ip())
        if wait <= 0:
            return False
        self.close_connection = True
        retry = max(1, int(wait + 0.999))
        self._send_bytes(429, json.dumps({"status": "error", "error": "Rate limit exceeded",
                                          "retry_after_seconds": retry}).encode("utf-8"),
                         "application/json; charset=utf-8",
                         {"Retry-After": str(retry), "Cache-Control": "no-store"})
        return True

    def _dispatch(self, handler):
        self._t0 = time.perf_counter()
        self._rid = uuid.uuid4().hex[:16]
        self._status = 0
        try:
            handler()
        finally:
            ms = (time.perf_counter() - self._t0) * 1000.0
            path = urllib.parse.urlparse(self.path).path
            if METRICS_ENABLED:
                metrics.record(self._status, ms,
                               self.command == "POST" and path == "/api/v1/translate")
            try:
                sys.stdout.write(json.dumps({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + "Z",
                    "request_id": self._rid, "method": self.command, "path": path[:200],
                    "status": self._status, "ms": round(ms, 1),
                    "client": self._client_hash()}) + "\n")
                sys.stdout.flush()
            except Exception:
                pass

    def _send_bytes(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra_headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _send_json(self, status, payload):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self._send_bytes(status, body, "application/json; charset=utf-8",
                         {"Cache-Control": "no-store"})

    def _send_file(self, file_path, cache_control):
        try:
            with open(file_path, "rb") as f:
                data = f.read()
        except OSError:
            self._send_json(404, {"status": "error", "message": "Not found"})
            return
        ext = os.path.splitext(file_path)[1].lower()
        ctype = MIME_TYPES.get(ext) or mimetypes.guess_type(file_path)[0] or "application/octet-stream"
        self._send_bytes(200, data, ctype, {"Cache-Control": cache_control})

    def _safe_host(self):
        host = (self.headers.get("Host") or "").strip()
        if host and _HOST_RE.match(host):
            return host
        return f"127.0.0.1:{PORT}"

    def _scheme(self):
        proto = (self.headers.get("X-Forwarded-Proto") or "").strip().lower()
        return "https" if proto == "https" else "http"

    # ---------- verbs ----------
    def do_OPTIONS(self):
        self._dispatch(self._options)

    def do_HEAD(self):
        self._dispatch(self._get)

    def do_GET(self):
        self._dispatch(self._get)

    def do_POST(self):
        self._dispatch(self._post)

    def _options(self):
        self.send_response(204)
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def _get(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/v1/health":
            self._send_json(200, {"status": "ok", "version": VERSION})
            return

        if path == "/api/v1/metrics":
            if METRICS_ENABLED:
                self._send_json(200, metrics.snapshot())
            else:
                self._send_json(404, {"status": "error", "message": "Not found"})
            return

        if path == "/app":
            self.send_response(301)
            self.send_header("Location", "/app/")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        if path.startswith("/app/"):
            rel = urllib.parse.unquote(path[len("/app/"):])
            if rel == "" or rel.endswith("/"):
                rel += "index.html"
            target = safe_join(WEB_DIR, rel)
            if target is None:
                self._send_json(403, {"status": "error", "message": "Forbidden"})
            elif not os.path.isfile(target):
                self._send_json(404, {"status": "error", "message": "Not found"})
            else:
                self._send_file(target, "no-cache")
            return

        if path.startswith("/extracted_images/"):
            filename = os.path.basename(urllib.parse.unquote(path))
            target = safe_join(IMAGES_DIR, filename) if filename else None
            if target is None or not os.path.isfile(target):
                self._send_json(404, {"status": "error", "message": "Image not found"})
            else:
                self._send_file(target, "public, max-age=604800, immutable")
            return

        if path.startswith("/api/v1/words/"):
            if self._rate_limited():
                return
            lemma = urllib.parse.unquote(path[len("/api/v1/words/"):]).strip()
            if not lemma or len(lemma) > 100:
                self._send_json(400, {"status": "error", "message": "Invalid word"})
                return
            tokens = nlp_engine.tokenize(lemma)
            norm_str = tokens[0] if tokens else lemma.lower()
            sign_info = translator.find_sign_by_word(norm_str)
            if sign_info:
                sign_info["image_available"] = image_exists(sign_info.get("ruta_imagen"))
                self._send_json(200, {"status": "success", "word": sign_info})
            else:
                self._send_json(404, {"status": "error",
                                      "message": f"Word '{lemma}' not found in LSRD dictionary"})
            return

        if path in ("/", ""):
            self._send_json(200, {
                "service": "Biblionx LSRD Translation API",
                "version": VERSION,
                "endpoints": [
                    "POST /api/v1/translate",
                    "GET /api/v1/words/{lemma}",
                    "GET /api/v1/health",
                    "GET /api/v1/metrics",
                    "GET /extracted_images/{id}.png",
                    "GET /app/",
                ],
            })
            return

        self._send_json(404, {"status": "error", "message": "Not found"})

    def _post(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/v1/translate":
            self._send_json(404, {"status": "error", "message": "Not found"})
            return
        if self._rate_limited():
            return

        try:
            content_length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            self._send_json(400, {"error": "Invalid Content-Length header"})
            return
        if content_length < 0:
            self._send_json(400, {"error": "Invalid Content-Length header"})
            return
        if content_length > MAX_BODY_BYTES:
            # Do not read the body; close the connection after replying.
            self.close_connection = True
            self._send_json(413, {"error": f"Request body too large (max {MAX_BODY_BYTES} bytes)"})
            return

        raw = self.rfile.read(content_length) if content_length else b""
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError):
            self._send_json(400, {"error": "Invalid JSON payload"})
            return
        if not isinstance(payload, dict):
            self._send_json(400, {"error": "JSON payload must be an object"})
            return

        texto = payload.get("texto", "")
        if not isinstance(texto, str) or not texto.strip():
            self._send_json(400, {"error": "The 'texto' field is required in the JSON payload"})
            return
        if len(texto) > MAX_TEXT_CHARS:
            self._send_json(413, {"error": f"'texto' exceeds {MAX_TEXT_CHARS} characters"})
            return

        try:
            nlp_result = nlp_engine.process(texto)
            sequence_signs = translator.translate_sequence(nlp_result["secuencia_lsrd"])
        except Exception:
            self.log_error("translation pipeline failed", )
            self._send_json(500, {"error": "Internal translation error"})
            return

        base = f"{self._scheme()}://{self._safe_host()}"
        for sign in sequence_signs:
            ruta = sign.get("ruta_imagen")
            sign.pop("url_imagen", None)
            if ruta and image_exists(ruta):
                sign["image_available"] = True
                name = os.path.basename(str(ruta).replace("\\", "/"))
                sign["url_imagen"] = f"{base}/extracted_images/{urllib.parse.quote(name)}"
            else:
                sign["image_available"] = False
        metrics.record_methods(sequence_signs)

        self._send_json(200, {
            "status": "success",
            "original_text": texto,
            "nlp_analysis": nlp_result,
            "total_senas": len(sequence_signs),
            "secuencia_senas": sequence_signs,
        })

    def log_message(self, fmt, *args):
        sys.stderr.write("[%s] %s\n" % (self.log_date_time_string(), fmt % args))


def run_server():
    httpd = ThreadingHTTPServer((HOST, PORT), LSRDApiHandler)
    httpd.daemon_threads = True
    print(f"Biblionx LSRD REST API Server running on http://{HOST}:{PORT} ...")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()


if __name__ == "__main__":
    run_server()
