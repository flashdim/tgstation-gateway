# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
ARG SELKIES_BASE_IMAGE=ghcr.io/selkies-project/selkies-egl-desktop:26.04@sha256:cee92447ae1445c0af4c26a73e32caa7d7cf31aed51b5c5e6549d94cc8fa8c9e

FROM scratch AS wine-prefix-cache

FROM ${SELKIES_BASE_IMAGE}

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG WINE_PACKAGE_VERSION=11.21~resolute-1

RUN if ! command -v wine >/dev/null 2>&1; then \
      selkies-privileged-files release && \
      mkdir -p /etc/apt/keyrings && \
      fetch-verified key https://dl.winehq.org/wine-builds/winehq.key \
        D43F640145369C51D786DDEA76F1A20FF987672F /etc/apt/keyrings/winehq.asc && \
      printf '%s\n' \
        'deb [arch=amd64 signed-by=/etc/apt/keyrings/winehq.asc] https://dl.winehq.org/wine-builds/ubuntu/ resolute main' \
        > /etc/apt/sources.list.d/winehq.list && \
      apt-get update && \
      apt-get install -y --install-recommends \
        "winehq-staging=${WINE_PACKAGE_VERSION}" \
        "wine-staging=${WINE_PACKAGE_VERSION}" cabextract unzip wget && \
      apt-get clean && rm -rf /var/lib/apt/lists/* && \
      selkies-privileged-files restore; \
    fi && \
    command -v wine && command -v cabextract && command -v unzip && command -v xvfb-run

# Use the same Winetricks revision on both desktop images for a controlled comparison.
RUN curl -fsSL --retry 3 \
      https://raw.githubusercontent.com/Winetricks/winetricks/f3890f670867b5ffbc3938726db45c0f7d16c8ba/src/winetricks \
      -o /usr/local/bin/winetricks && \
    echo '672a1ff4442e8691a3ffc0e6860137e201a1d1227e9b3044245f1731e9e9837e  /usr/local/bin/winetricks' | sha256sum -c - && \
    chmod 755 /usr/local/bin/winetricks

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
