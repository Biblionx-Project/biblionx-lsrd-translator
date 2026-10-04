# Biblionx LSRD translator - API + web UI (stdlib only, no pip install needed).
ARG PYTHON_VERSION=3.13
FROM python:${PYTHON_VERSION}-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    BIBLIONX_HOST=0.0.0.0 \
    BIBLIONX_PORT=8000 \
    BIBLIONX_IMAGES_DIR=/data/images

RUN useradd --system --uid 10001 --no-create-home biblionx \
    && mkdir -p /app /data/images

WORKDIR /app
COPY . /app
RUN chown -R root:root /app && chmod -R a+rX,go-w /app

USER biblionx
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request as u; u.urlopen('http://127.0.0.1:%s/api/v1/health' % os.environ.get('BIBLIONX_PORT','8000'), timeout=4).read()"]

CMD ["python", "backend_api/server.py"]
