# Test landing page. Build from the repository root:
#   docker build -f landing/Dockerfile -t tgstation-gateway-landing:local .
FROM python:3.12-alpine@sha256:c5ba3deef00c7758561a0f03c26f44f10589263d40e732b8748e0d1f38f6dd89

COPY landing/index.html landing/page.js landing/wizard.js landing/narsie.js landing/style.css /srv/landing/
COPY landing/assets/sprites/ /srv/landing/assets/sprites/
COPY landing/assets/ATTRIBUTION.md landing/assets/layer1.webp /srv/landing/assets/
COPY landing/assets/banners/alert.svg /srv/landing/assets/banners/alert.svg
COPY landing/server.py /opt/landing/server.py

ENV GATEWAY_PLAY_HOST=localhost:8080 \
    GATEWAY_PLAY_SCHEME= \
    GATEWAY_SLOT_COUNT=1 \
    GATEWAY_ACCOUNT_PREFIX=LGplayer \
    GATEWAY_SLOT_PATH=/ \
    GATEWAY_ACTIVE_SLOTS=

USER 65534:65534
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python3", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/slots.js', timeout=4)"]
CMD ["python3", "/opt/landing/server.py"]
