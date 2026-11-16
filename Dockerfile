# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
FROM scratch AS wine-prefix-cache

FROM ghcr.io/selkies-project/selkies/base:2.2.1-ubuntu26.04@sha256:4b70c739ea5aa650dd35a143d92c4bf80b7a527f2c66ee88718b08a5211267ff

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG WINE_PACKAGE_VERSION=10.0~repack-12ubuntu1

RUN selkies-privileged-files release && \
    dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      "wine=${WINE_PACKAGE_VERSION}" "wine32:i386=${WINE_PACKAGE_VERSION}" \
      "wine64=${WINE_PACKAGE_VERSION}" cabextract unzip wget xz-utils \
      openbox trayer libfreetype6:i386 libfontconfig1:i386 \
      libgnutls30t64:i386 libgssapi-krb5-2:i386 libvulkan1:i386 && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    selkies-privileged-files restore

RUN curl -fsSL --retry 3 \
      https://github.com/Kron4ek/Wine-Builds/releases/download/proton-11.0-2/wine-proton-11.0-2-amd64.tar.xz \
      -o /tmp/wine-proton.tar.xz && \
    echo '51e1b54068c242c0a59c329674afe4b0ae03d313516a535be4acd1c5f3277e9b  /tmp/wine-proton.tar.xz' | sha256sum -c - && \
    mkdir -p /opt/wine-proton && \
    tar -xJf /tmp/wine-proton.tar.xz --strip-components=1 -C /opt/wine-proton && \
    test -x /opt/wine-proton/bin/wine && \
    test -x /opt/wine-proton/lib/wine/i386-unix/wine-preloader && \
    rm /tmp/wine-proton.tar.xz

# Pin the Winetricks revision used by the desktop experiment.
RUN curl -fsSL --retry 3 \
      https://raw.githubusercontent.com/Winetricks/winetricks/f3890f670867b5ffbc3938726db45c0f7d16c8ba/src/winetricks \
      -o /usr/local/bin/winetricks && \
    echo '672a1ff4442e8691a3ffc0e6860137e201a1d1227e9b3044245f1731e9e9837e  /usr/local/bin/winetricks' | sha256sum -c - && \
    chmod 755 /usr/local/bin/winetricks

COPY --chmod=755 container/install-client.sh /usr/local/bin/install-client

USER 1000
ENV PATH=/opt/wine-proton/bin:${PATH} \
    WINEPREFIX=/home/ubuntu/.wine \
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
COPY --chmod=755 container/install-graphics.sh /usr/local/bin/install-graphics
ARG BYOND_VERSION=516.1688
ARG BYOND_SHA256=""
ENV BYOND_VERSION=${BYOND_VERSION}

RUN /usr/local/bin/install-byond
RUN xvfb-run -a /usr/local/bin/install-graphics

USER root
RUN install -d -o 1000 -g 1000 /etc/service/byond /etc/service/window-manager /etc/service/byond-tray && \
    install -d -o 1000 -g 1000 -m 1777 /tmp/.X11-unix
COPY --chown=1000:1000 --chmod=755 container/run-client.sh /etc/service/byond/run
COPY --chown=1000:1000 --chmod=755 container/run-window-manager.sh /etc/service/window-manager/run
COPY --chown=1000:1000 --chmod=755 container/run-tray.sh /etc/service/byond-tray/run
COPY --chmod=755 container/healthcheck.sh /usr/local/bin/healthcheck
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck"]
