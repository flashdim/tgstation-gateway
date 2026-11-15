# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
FROM scratch AS wine-prefix-cache

FROM ghcr.io/selkies-project/selkies-egl-desktop:26.04@sha256:cee92447ae1445c0af4c26a73e32caa7d7cf31aed51b5c5e6549d94cc8fa8c9e

SHELL ["/bin/sh", "-c"]

RUN command -v wine && command -v winetricks && command -v lutris && \
    command -v cabextract && command -v unzip && command -v xvfb-run

COPY --chmod=755 container/install-client.sh /usr/local/bin/install-client

USER 1000
ENV WINEPREFIX=/home/ubuntu/.wine \
    WINEARCH=win64 \
    SELKIES_ENABLE_HTTPS=false \
    SELKIES_ENABLE_BASIC_AUTH=false \
    SELKIES_COMMAND_ENABLED=false

RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \
    if [ -f /tmp/wine-prefix-cache/prefix.tar.gz ]; then \
      mkdir -p "$WINEPREFIX" && \
      tar -xzf /tmp/wine-prefix-cache/prefix.tar.gz -C "$WINEPREFIX" && \
      test -s "$WINEPREFIX/system.reg" && \
      find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
        -name msedgewebview2.exe -print -quit | grep -q . || \
        { echo "Invalid cached Wine prefix" >&2; exit 1; }; \
    else \
      xvfb-run -a /usr/local/bin/install-client; \
    fi

COPY --chmod=755 container/install-byond.sh /usr/local/bin/install-byond
ARG BYOND_VERSION=516.1688
ARG BYOND_SHA256=""
ENV BYOND_VERSION=${BYOND_VERSION}

RUN /usr/local/bin/install-byond

USER root
RUN install -d -o 1000 -g 1000 /etc/service/byond
COPY --chown=1000:1000 --chmod=755 container/run-client.sh /etc/service/byond/run
COPY --chmod=755 container/healthcheck.sh /usr/local/bin/healthcheck
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck"]
