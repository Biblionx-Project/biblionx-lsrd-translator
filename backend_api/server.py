#!/usr/bin/env python3
"""
HTTP REST API server for the Dominican Sign Language (LSRD) translator.
Built on Python's http.server (standard library only).

Endpoints:
  - POST /api/v1/translate      -> {"texto": "..."}
  - GET  /api/v1/words/{lemma}
  - GET  /api/v1/health
  - GET  /extracted_images/{filename}
  - GET  /app/ and /app/{file}  -> static web UI from backend_api/web/

Environment variables:
  - BIBLIONX_HOST         bind address (default 127.0.0.1)
  - BIBLIONX_PORT         bind port (default 8000)
  - BIBLIONX_CORS_ORIGIN  value of Access-Control-Allow-Origin (default '*')
"""

import os
import re
import sys
import json
import mimetypes
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from nlp_engine import LSRDNlpEngine  # noqa: E402
from translator import LSRDTranslator  # noqa: E402

VERSION = "1.1.0"
HOST = os.environ.get("BIBLIONX_HOST", "127.0.0.1")
try:
    PORT = int(os.environ.get("BIBLIONX_PORT", "8000"))
except ValueError:
    PORT = 8000
CORS_ORIGIN = os.environ.get("BIBLIONX_CORS_ORIGIN", "*")

MAX_BODY_BYTES = 64 * 1024
MAX_TEXT_CHARS = 2000

IMAGES_DIR = os.path.join(BASE_DIR, "extracted_images")
WEB_DIR = os.path.join(BASE_DIR, "web")

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


class LSRDApiHandler(BaseHTTPRequestHandler):
    server_version = "BiblionxAPI/" + VERSION
    protocol_version = "HTTP/1.1"

    # ---------- helpers ----------
    def _set_cors_headers(self):
        self.send_header("Access-Control-Allow-Origin", CORS_ORIGIN)
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        if CORS_ORIGIN != "*":
            self.send_header("Vary", "Origin")

    def _send_bytes(self, status, body, content_type, extra_headers=None):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self._set_cors_headers()
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
        self.send_response(204)
        self._set_cors_headers()
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_HEAD(self):
        self.do_GET()

    def do_GET(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/api/v1/health":
            self._send_json(200, {"status": "ok", "version": VERSION})
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
            lemma = urllib.parse.unquote(path[len("/api/v1/words/"):]).strip()
            if not lemma or len(lemma) > 100:
                self._send_json(400, {"status": "error", "message": "Invalid word"})
                return
            tokens = nlp_engine.tokenize(lemma)
            norm_str = tokens[0] if tokens else lemma.lower()
            sign_info = translator.find_sign_by_word(norm_str)
            if sign_info:
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
                    "GET /extracted_images/{id}.png",
                    "GET /app/",
                ],
            })
            return

        self._send_json(404, {"status": "error", "message": "Not found"})

    def do_POST(self):
        path = urllib.parse.urlparse(self.path).path
        if path != "/api/v1/translate":
            self._send_json(404, {"status": "error", "message": "Not found"})
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
            if ruta:
                sign["url_imagen"] = f"{base}/{urllib.parse.quote(str(ruta).lstrip('/'))}"

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
