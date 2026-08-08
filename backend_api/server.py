#!/usr/bin/env python3
"""
Servidor API REST HTTP de la Lengua de Señas Dominicana (LSRD).
Construido con Python http.server (compatible sin dependencias externas).
Endpoints:
  - POST /api/v1/translate -> {"texto": "..."}
  - GET  /api/v1/words/{lemma}
  - GET  /extracted_images/{filename}
"""

import os
import json
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

from nlp_engine import LSRDNlpEngine
from translator import LSRDTranslator

nlp_engine = LSRDNlpEngine()
translator = LSRDTranslator()

PORT = 8000

class LSRDApiHandler(BaseHTTPRequestHandler):

    def _set_cors_headers(self):
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type, Authorization')

    def do_OPTIONS(self):
        self.send_response(200)
        self._set_cors_headers()
        self.end_headers()

    def do_GET(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path
        
        # Endpoint: Servir imágenes estáticas de señas
        if path.startswith('/extracted_images/'):
            filename = os.path.basename(path)
            file_path = os.path.join('extracted_images', filename)
            if os.path.exists(file_path):
                self.send_response(200)
                self.send_header('Content-Type', 'image/png')
                self._set_cors_headers()
                self.end_headers()
                with open(file_path, 'rb') as img_f:
                    self.wfile.write(img_f.read())
            else:
                self.send_response(404)
                self.end_headers()
            return
            
        # Endpoint: GET /api/v1/words/{lemma}
        if path.startswith('/api/v1/words/'):
            lemma = urllib.parse.unquote(path[len('/api/v1/words/'):]).strip()
            norm_lemma = nlp_engine.tokenize(lemma)
            norm_str = norm_lemma[0] if norm_lemma else lemma.lower()
            
            sign_info = translator.find_sign_by_word(norm_str)
            if sign_info:
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "success", "word": sign_info}, ensure_ascii=False).encode('utf-8'))
            else:
                self.send_response(404)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"status": "error", "message": f"Word '{lemma}' not found in LSRD dictionary"}, ensure_ascii=False).encode('utf-8'))
            return

        # Default root
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self._set_cors_headers()
        self.end_headers()
        self.wfile.write(json.dumps({
            "service": "Biblionx LSRD Translation API",
            "version": "1.0.0",
            "endpoints": [
                "POST /api/v1/translate",
                "GET /api/v1/words/{lemma}",
                "GET /extracted_images/{id}.png"
            ]
        }, ensure_ascii=False).encode('utf-8'))

    def do_POST(self):
        parsed_url = urllib.parse.urlparse(self.path)
        path = parsed_url.path

        # Endpoint: POST /api/v1/translate
        if path == '/api/v1/translate':
            content_length = int(self.headers.get('Content-Length', 0))
            post_data = self.rfile.read(content_length).decode('utf-8')
            
            try:
                payload = json.loads(post_data)
                texto = payload.get("texto", "")
            except Exception:
                texto = ""

            if not texto:
                self.send_response(400)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self._set_cors_headers()
                self.end_headers()
                self.wfile.write(json.dumps({"error": "Campo 'texto' es requerido en el JSON payload"}, ensure_ascii=False).encode('utf-8'))
                return

            # Pipeline NLP & Translation
            nlp_result = nlp_engine.process(texto)
            sequence_signs = translator.translate_sequence(nlp_result['secuencia_lsrd'])

            # Add full image URL host
            host = self.headers.get('Host', f'127.0.0.1:{PORT}')
            for sign in sequence_signs:
                if sign.get('ruta_imagen'):
                    sign['url_imagen'] = f"http://{host}/{sign['ruta_imagen']}"

            response_payload = {
                "status": "success",
                "original_text": texto,
                "nlp_analysis": nlp_result,
                "total_senas": len(sequence_signs),
                "secuencia_senas": sequence_signs
            }

            self.send_response(200)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self._set_cors_headers()
            self.end_headers()
            self.wfile.write(json.dumps(response_payload, ensure_ascii=False).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

def run_server():
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, LSRDApiHandler)
    print(f"Biblionx LSRD REST API Server running on port {PORT}...")
    httpd.serve_forever()

if __name__ == "__main__":
    run_server()
