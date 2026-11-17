# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
FROM scratch AS wine-prefix-cache
FROM scratch AS ge-proton-download-cache

FROM ghcr.io/selkies-project/selkies/base:2.2.1-ubuntu26.04@sha256:4b70c739ea5aa650dd35a143d92c4bf80b7a527f2c66ee88718b08a5211267ff

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG WINE_PACKAGE_VERSION=10.0~repack-12ubuntu1
ARG GE_PROTON_VERSION=GE-Proton10-34

RUN set -eu; \
    selkies-privileged-files release; \
    dpkg --add-architecture i386; \
    apt-get update; \
    apt-get install -y --no-install-recommends \
      "wine=$WINE_PACKAGE_VERSION" "wine32:i386=$WINE_PACKAGE_VERSION" \
      "wine64=$WINE_PACKAGE_VERSION" cabextract unzip wget xz-utils \
      openbox trayer fonts-liberation python3 libfreetype6:i386 libfontconfig1:i386 \
      libgnutls30t64:i386 libgssapi-krb5-2:i386 libvulkan1:i386 \
      libwayland-cursor0 libwayland-cursor0:i386; \
    apt-get clean; rm -rf /var/lib/apt/lists/*; \
    selkies-privileged-files restore

COPY container/download-ge-proton.sh container/ge-proton.env /tmp/ge-proton-download/
RUN --mount=type=bind,from=ge-proton-download-cache,target=/tmp/ge-proton-download-cache \
    set -eu; \
    if [ -f "/tmp/ge-proton-download-cache/$GE_PROTON_VERSION.tar.gz" ]; then \
      cp "/tmp/ge-proton-download-cache/$GE_PROTON_VERSION.tar.gz" /tmp/ge-proton.tar.gz; \
    fi; \
    build_version="$GE_PROTON_VERSION"; \
    . /tmp/ge-proton-download/ge-proton.env; \
    test "$build_version" = "$GE_PROTON_VERSION"; \
    sh /tmp/ge-proton-download/download-ge-proton.sh /tmp; \
    mkdir -p /opt/ge-proton; \
    tar -xzf "/tmp/$GE_PROTON_VERSION.tar.gz" --strip-components=1 -C /opt/ge-proton; \
    test -x /opt/ge-proton/proton; \
    test -x /opt/ge-proton/files/bin/wine; \
    test -x /opt/ge-proton/files/bin/wine64; \
    test -x /opt/ge-proton/files/bin/wineserver; \
    chown -R 1000:1000 /opt/ge-proton; \
    rm "/tmp/$GE_PROTON_VERSION.tar.gz"

# Build-time gate shared by CI and releases. Do not fake SONAME links.
RUN set -eu; \
    for package in wine wine32:i386 wine64; do \
      test "$(dpkg-query -W -f='${Version}' "$package")" = "$WINE_PACKAGE_VERSION"; \
    done; \
    test -x /opt/ge-proton/files/bin/wine; \
    test -x /opt/ge-proton/files/bin/wine64; \
    test -x /opt/ge-proton/files/bin/wineserver; \
    for architecture in i386 x86_64; do \
      directory="/opt/ge-proton/files/lib/wine/$architecture-unix"; \
      for library in libfreetype.so.6 libfontconfig.so.1 libgnutls.so.30 \
          libgssapi_krb5.so.2 libGL.so.1 libEGL.so.1 libvulkan.so.1 \
          libwayland-cursor.so.0; do \
        test -r "/usr/lib/$architecture-linux-gnu/$library" || \
          { echo "Missing or unreadable /usr/lib/$architecture-linux-gnu/$library" >&2; exit 1; }; \
      done; \
      test -d "$directory" || { echo "Missing $architecture Unix modules" >&2; exit 1; }; \
      for module in ntdll.so win32u.so winex11.so winewayland.so \
          winealsa.so winepulse.so winevulkan.so; do \
        test -r "$directory/$module" || \
          { echo "Missing $directory/$module" >&2; exit 1; }; \
        dependencies="$(LD_LIBRARY_PATH="$directory:/opt/ge-proton/files/lib/$architecture-linux-gnu:/opt/ge-proton/files/lib/wine" ldd "$directory/$module")"; \
        if printf '%s\n' "$dependencies" | grep 'not found'; then \
          echo "Missing dependencies for $directory/$module" >&2; exit 1; \
        fi; \
      done; \
      if [ -f "$directory/winegstreamer.so" ]; then \
        dependencies="$(LD_LIBRARY_PATH="$directory:/opt/ge-proton/files/lib/$architecture-linux-gnu:/opt/ge-proton/files/lib/wine" ldd "$directory/winegstreamer.so")"; \
        if printf '%s\n' "$dependencies" | grep 'not found'; then \
          echo "Missing dependencies for $directory/winegstreamer.so" >&2; exit 1; \
        fi; \
      fi; \
    done; \
    for binary in /opt/ge-proton/files/bin/wine /opt/ge-proton/files/bin/wine64 \
        /opt/ge-proton/files/bin/wineserver; do \
      test -x "$binary"; \
      dependencies="$(LD_LIBRARY_PATH=/opt/ge-proton/files/lib/x86_64-linux-gnu:/opt/ge-proton/files/lib/wine ldd "$binary")"; \
      if printf '%s\n' "$dependencies" | grep 'not found'; then \
        echo "Missing dependencies for $binary" >&2; exit 1; \
      fi; \
    done

# Pin the Winetricks revision used by the desktop experiment.
RUN curl -fsSL --retry 3 \
      https://raw.githubusercontent.com/Winetricks/winetricks/f3890f670867b5ffbc3938726db45c0f7d16c8ba/src/winetricks \
      -o /usr/local/bin/winetricks && \
    echo '672a1ff4442e8691a3ffc0e6860137e201a1d1227e9b3044245f1731e9e9837e  /usr/local/bin/winetricks' | sha256sum -c - && \
    chmod 755 /usr/local/bin/winetricks

COPY --chmod=755 container/install-client.sh /usr/local/bin/install-client
COPY --chmod=755 container/proton-wine.sh /usr/local/bin/proton-wine

USER 1000
ARG SELKIES_WAYLAND=false
ENV PATH=/opt/ge-proton/files/bin:${PATH} \
    GE_PROTON_PATH=/opt/ge-proton \
    GE_PROTON_VERSION=${GE_PROTON_VERSION} \
    WINE=/usr/local/bin/proton-wine \
    WINELOADER=/opt/ge-proton/files/bin/wine \
    WINESERVER=/opt/ge-proton/files/bin/wineserver \
    WINE_PACKAGE_VERSION=${WINE_PACKAGE_VERSION} \
    STEAM_COMPAT_DATA_PATH=/home/ubuntu/.wine \
    STEAM_COMPAT_CLIENT_INSTALL_PATH=/home/ubuntu/.steam/steam \
    UMU_ID=umu-default \
    WINEPREFIX=/home/ubuntu/.wine/pfx \
    WINEARCH=win64 \
    SELKIES_WAYLAND=${SELKIES_WAYLAND} \
    SELKIES_ENABLE_HTTPS=false \
    SELKIES_ENABLE_BASIC_AUTH=false \
    SELKIES_MANUAL_WIDTH=1920 \
    SELKIES_MANUAL_HEIGHT=1080 \
    SELKIES_COMMAND_ENABLED=false

RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \
    if [ -f /tmp/wine-prefix-cache/prefix.tar.gz ]; then \
      mkdir -p "$WINEPREFIX" && \
      tar -xzf /tmp/wine-prefix-cache/prefix.tar.gz -C "$WINEPREFIX" && \
      test "$(cat "$WINEPREFIX/.gateway-ge-proton-version")" = "$GE_PROTON_VERSION" && \
      test -s "$WINEPREFIX/system.reg" && \
      find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
        -name msedgewebview2.exe -print -quit | grep -q . || \
        { echo "Invalid cached Wine prefix" >&2; exit 1; }; \
    else \
      xvfb-run -a /usr/local/bin/install-client; \
    fi && \
    printf '%s\n' "$GE_PROTON_VERSION" > "$WINEPREFIX/.gateway-ge-proton-version"

COPY --chmod=755 container/install-byond.sh /usr/local/bin/install-byond
COPY --chmod=755 container/install-graphics.sh /usr/local/bin/install-graphics
ARG BYOND_VERSION=516.1689
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
