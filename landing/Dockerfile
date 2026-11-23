# Static test landing page. Build from the repository root:
#   docker build -f landing/Dockerfile -t tgstation-gateway-landing:local .
FROM python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89

COPY landing/index.html landing/page.js landing/slots.js landing/style.css landing/clown.webp /srv/landing/
COPY assets/ATTRIBUTION.md /srv/landing/ATTRIBUTION.md

USER 65534:65534
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/', timeout=4)"]
CMD ["python3", "-m", "http.server", "8000", "--bind", "0.0.0.0", "--directory", "/srv/landing"]
