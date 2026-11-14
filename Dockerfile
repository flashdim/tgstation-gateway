# syntax=docker/dockerfile:1
# The first milestone is one BYOND client per container, not a session manager.
FROM ghcr.io/selkies-project/selkies/desktop:2.2.1-ubuntu26.04@sha256:f7a7b11dadbeca42114a09ae390457cd7e50af2b8f534c3ebae7b1d14b9851a4

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG WINE_PACKAGE_VERSION=11.0.0.0~resolute-1

RUN selkies-privileged-files release && \
    mkdir -p /etc/apt/keyrings && \
    fetch-verified key https://dl.winehq.org/wine-builds/winehq.key \
      D43F640145369C51D786DDEA76F1A20FF987672F /etc/apt/keyrings/winehq.asc && \
    printf '%s\n' \
      'deb [arch=amd64 signed-by=/etc/apt/keyrings/winehq.asc] https://dl.winehq.org/wine-builds/ubuntu/ resolute main' \
      > /etc/apt/sources.list.d/winehq.list && \
    apt-get update && \
    apt-get install -y --install-recommends \
      "winehq-stable=${WINE_PACKAGE_VERSION}" cabextract unzip wget && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    selkies-privileged-files restore

# The script is pinned; its installers can still change upstream. Fail rather
# than bypassing Winetricks' integrity checks if an upstream download changes.
RUN curl -fsSL --retry 3 \
      https://raw.githubusercontent.com/Winetricks/winetricks/20260125/src/winetricks \
      -o /usr/local/bin/winetricks && \
    echo '431f82fc74000e6c864409f1d8fb495d696c03928808e3e8acffc45179312a7b  /usr/local/bin/winetricks' | sha256sum -c - && \
    chmod 755 /usr/local/bin/winetricks

COPY --chmod=755 container/install-client.sh /usr/local/bin/install-client
RUN install -d -o 1000 -g 1000 /etc/service/byond
COPY --chown=1000:1000 --chmod=755 container/run-client.sh /etc/service/byond/run

USER 1000
ENV WINEPREFIX=/home/ubuntu/.wine \
    WINEARCH=win64 \
    SELKIES_COMMAND_ENABLED=false

# Installers are supplied locally and mounted only during this build step.
RUN --mount=type=bind,source=installers,target=/installers,readonly \
    xvfb-run -a /usr/local/bin/install-client
