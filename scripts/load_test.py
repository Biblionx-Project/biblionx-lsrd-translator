#!/usr/bin/env python3
"""Minimal load test for a running Biblionx API (stdlib threads only).

Usage:
    python scripts/load_test.py --url http://127.0.0.1:8000 --concurrency 8 --requests 400

Sends POST /api/v1/translate with rotating Spanish sentences and reports
latency percentiles, error count and HTTP 429 count. Exit code 1 if any
non-429 error occurred.
"""

import argparse
import json
import threading
import time
import urllib.error
import urllib.request

SENTENCES = [
    "Buenos días, ¿cómo estás?",
    "Hola, me llamo Ana y vivo en Santiago.",
    "Gracias por tu ayuda.",
    "Mañana voy a la escuela con mis amigos.",
    "¿Dónde está el hospital más cercano?",
    "Necesito comprar comida para la familia.",
    "El doctor dice que debo descansar.",
    "Quiero aprender lengua de señas dominicana.",
]


def percentile(sorted_vals, p):
    if not sorted_vals:
        return 0.0
    idx = min(len(sorted_vals) - 1, max(0, int(round(p / 100 * len(sorted_vals) + 0.5)) - 1))
    return sorted_vals[idx]


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="server base URL")
    ap.add_argument("--concurrency", type=int, default=8)
    ap.add_argument("--requests", type=int, default=200, help="total requests")
    args = ap.parse_args()

    endpoint = args.url.rstrip("/") + "/api/v1/translate"
    lock = threading.Lock()
    counter = {"next": 0}
    latencies, stats = [], {"ok": 0, "errors": 0, "rate_limited": 0}

    def worker():
        while True:
            with lock:
                i = counter["next"]
                if i >= args.requests:
                    return
                counter["next"] += 1
            body = json.dumps({"texto": SENTENCES[i % len(SENTENCES)]}).encode("utf-8")
            req = urllib.request.Request(endpoint, data=body, method="POST",
                                         headers={"Content-Type": "application/json"})
            t0 = time.perf_counter()
            kind = "ok"
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    r.read()
                    if r.status != 200:
                        kind = "errors"
            except urllib.error.HTTPError as e:
                e.read()
                kind = "rate_limited" if e.code == 429 else "errors"
            except Exception:
                kind = "errors"
            dt = (time.perf_counter() - t0) * 1000
            with lock:
                latencies.append(dt)
                stats[kind] += 1

    t_start = time.perf_counter()
    threads = [threading.Thread(target=worker) for _ in range(max(1, args.concurrency))]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - t_start

    lat = sorted(latencies)
    print(json.dumps({
        "url": endpoint,
        "concurrency": args.concurrency,
        "requests": len(lat),
        "ok": stats["ok"],
        "errors": stats["errors"],
        "http_429": stats["rate_limited"],
        "wall_seconds": round(wall, 3),
        "throughput_rps": round(len(lat) / wall, 1) if wall else 0,
        "latency_ms": {
            "p50": round(percentile(lat, 50), 2),
            "p95": round(percentile(lat, 95), 2),
            "p99": round(percentile(lat, 99), 2),
            "max": round(lat[-1], 2) if lat else 0,
        },
    }, indent=2))
    return 1 if stats["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
