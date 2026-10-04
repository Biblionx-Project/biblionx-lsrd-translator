# Deployment

Biblionx is pure Python standard library (3.13+; developed on 3.14). No `pip install` is needed.

## 1. Run locally

```bash
python backend_api/server.py          # http://127.0.0.1:8000/app/
```

Health check: `curl http://127.0.0.1:8000/api/v1/health`.

## 2. Sign images (not in git)

The sign images (`extracted_images/`) were only extraction artifacts used to build `lsrd_dictionary.db`.
They are **not** in the repository. To show images, provide the folder from the original extraction and
point `BIBLIONX_IMAGES_DIR` at it (default: `<repo root>/extracted_images`). Without images, translations
still work: each sign gets `"image_available": false` and the UI shows a text card (word + movement description).

## 3. Docker

```bash
docker build -t biblionx-lsrd .
docker run -d --name biblionx -p 8000:8000 \
  -v /path/to/extracted_images:/data/images:ro \
  --env-file .env biblionx-lsrd
```

The container runs as a non-root user, binds `0.0.0.0:8000`, and has a `HEALTHCHECK` on `/api/v1/health`.
`--env-file .env` is optional; omit it to run without the AI fallback.

## 4. Docker Compose with domain and HTTPS

Point a DNS A/AAAA record at the server and open ports 80 and 443.

```bash
cp .env.example .env                      # optional: AI fallback settings
export BIBLIONX_DOMAIN=biblionx.example.org
export BIBLIONX_IMAGES_HOST_DIR=/srv/biblionx/extracted_images   # default ../extracted_images
docker compose -f deploy/docker-compose.yml up -d --build
```

Caddy obtains and renews certificates automatically. The `app` service is only reachable on the internal
compose network (not published on the host). `BIBLIONX_TRUST_PROXY=1` makes the app use the client IP
forwarded by Caddy (needed for per-client rate limiting).

## 5. Environment variables

See `.env.example` for the full, commented list (LLM provider, model, keys, `BIBLIONX_LLM_MAX_CALLS`,
`BIBLIONX_LLM_RATE_PER_MIN`, `BIBLIONX_CORS_ORIGIN`). Deployment-related:

| Variable | Default | Purpose |
|---|---|---|
| `BIBLIONX_HOST` | `127.0.0.1` (`0.0.0.0` in Docker) | Bind address |
| `BIBLIONX_PORT` | `8000` | Bind port |
| `BIBLIONX_IMAGES_DIR` | `<repo>/extracted_images` (`/data/images` in Docker) | Sign images folder |
| `BIBLIONX_TRUST_PROXY` | `0` (`1` in compose) | Trust forwarded client IP from the reverse proxy |
| `BIBLIONX_CORS_ORIGIN` | unset (same-origin) | Comma-separated allowed origins, or `*` |
| `BIBLIONX_DOMAIN` | required in compose | Public domain for Caddy HTTPS |
| `BIBLIONX_IMAGES_HOST_DIR` | `../extracted_images` | Host folder mounted read-only (compose only) |

The browser extension calls the API from its service worker (host permissions), so it needs no CORS.

## 6. AI fallback cost guard

There is no default cap on AI calls (`BIBLIONX_LLM_MAX_CALLS=0` = unlimited) so demos can translate
broadly; results are cached. For any public deployment:

- Set `BIBLIONX_LLM_RATE_PER_MIN=30` (per-client AI rate limit; `0` = off).
- Set a **monthly spend limit** in the provider console (Anthropic/OpenAI).
- Keep `BIBLIONX_LLM_MAX_CALLS` at `0` for demos, or set a high value to bound a single process.
