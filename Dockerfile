# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
FROM scratch AS wine-prefix-cache

FROM ghcr.io/selkies-project/selkies/base:2.2.1-ubuntu26.04@sha256:4b70c739ea5aa650dd35a143d92c4bf80b7a527f2c66ee88718b08a5211267ff

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG WINE_PACKAGE_VERSION=11.22~resolute-1

RUN set -eu; \
    selkies-privileged-files release; \
    dpkg --add-architecture i386; \
    test "$WINE_PACKAGE_VERSION" = "11.22~resolute-1"; \
    apt-get update; \
    apt-get install -y --no-install-recommends ca-certificates curl gpg; \
    install -d -m 0755 /etc/apt/keyrings; \
    curl -fsSL --retry 3 https://dl.winehq.org/wine-builds/winehq.key \
      -o /etc/apt/keyrings/winehq.key; \
    gpg --batch --yes --dearmor -o /etc/apt/keyrings/winehq-archive.gpg /etc/apt/keyrings/winehq.key; \
    rm /etc/apt/keyrings/winehq.key; \
    curl -fsSL --retry 3 \
      https://dl.winehq.org/wine-builds/ubuntu/dists/resolute/winehq-resolute.sources \
      -o /etc/apt/sources.list.d/winehq-resolute.sources; \
    sed -i 's|/etc/apt/keyrings/winehq-archive.key|/etc/apt/keyrings/winehq-archive.gpg|g' \
      /etc/apt/sources.list.d/winehq-resolute.sources; \
    grep -Fx 'Signed-By: /etc/apt/keyrings/winehq-archive.gpg' \
      /etc/apt/sources.list.d/winehq-resolute.sources; \
    apt-get update; \
    apt-get install -y --install-recommends \
      "winehq-staging=$WINE_PACKAGE_VERSION"; \
    apt-get install -y --no-install-recommends \
      cabextract unzip wget xz-utils openbox trayer fonts-liberation \
      libfreetype6:i386 libfontconfig1:i386 libgnutls30t64:i386 \
      libgssapi-krb5-2:i386 libvulkan1:i386 libgstreamer-gl1.0-0:i386; \
    apt-get clean; rm -rf /var/lib/apt/lists/*; \
    selkies-privileged-files restore

# Build-time gate shared by CI and releases. WineHQ supports both classic and
# new WoW64 layouts; only the former has i386 Unix modules. Do not fake SONAME links.
RUN set -eu; \
    test "$(dpkg-query -W -f='${Version}' winehq-staging)" = "$WINE_PACKAGE_VERSION"; \
    test -x /opt/wine-staging/bin/wine; \
    for architecture in i386 x86_64; do \
      for library in libfreetype.so.6 libfontconfig.so.1 libgnutls.so.30 \
          libgssapi_krb5.so.2 libGL.so.1 libEGL.so.1 libvulkan.so.1; do \
        test -r "/usr/lib/$architecture-linux-gnu/$library" || \
          { echo "Missing or unreadable /usr/lib/$architecture-linux-gnu/$library" >&2; exit 1; }; \
      done; \
      find /opt/wine-staging/lib /opt/wine-staging/lib64 \
        -path "*/$architecture-windows/ntdll.dll" -type f -print 2>/dev/null | grep -q . || \
        { echo "Missing $architecture Windows modules" >&2; exit 1; }; \
      directory=""; \
      for libdir in lib lib64; do \
        candidate="/opt/wine-staging/$libdir/wine/$architecture-unix"; \
        if [ -d "$candidate" ]; then \
          candidate="$(readlink -f "$candidate")"; \
          test -z "$directory" || test "$directory" = "$candidate"; \
          directory="$candidate"; \
        fi; \
      done; \
      if [ -z "$directory" ]; then \
        test "$architecture" = i386 || \
          { echo "Missing $architecture Unix modules" >&2; exit 1; }; \
        for module in wow64.dll wow64cpu.dll; do \
          find /opt/wine-staging/lib /opt/wine-staging/lib64 \
            -path "*/x86_64-windows/$module" -type f -print 2>/dev/null | grep -q . || \
            { echo "Missing new WoW64 component $module" >&2; exit 1; }; \
        done; \
        continue; \
      fi; \
      for loader in wine wine-preloader; do \
        test -x "$directory/$loader"; \
        dependencies="$(ldd "$directory/$loader")"; \
        if printf '%s\n' "$dependencies" | grep 'not found'; then \
          echo "Missing dependencies for $directory/$loader" >&2; exit 1; \
        fi; \
      done; \
      for module in ntdll.so win32u.so winex11.so winewayland.so \
          winealsa.so winepulse.so winevulkan.so; do \
        dependencies="$(LD_LIBRARY_PATH="$directory" ldd "$directory/$module")"; \
        if printf '%s\n' "$dependencies" | grep 'not found'; then \
          echo "Missing dependencies for $directory/$module" >&2; exit 1; \
        fi; \
      done; \
      if [ -f "$directory/winegstreamer.so" ]; then \
        dependencies="$(LD_LIBRARY_PATH="$directory" ldd "$directory/winegstreamer.so")"; \
        if printf '%s\n' "$dependencies" | grep 'not found'; then \
          echo "Missing dependencies for $directory/winegstreamer.so" >&2; exit 1; \
        fi; \
      fi; \
    done; \
    for binary in /opt/wine-staging/bin/wineserver; do \
      test -x "$binary"; \
      dependencies="$(ldd "$binary")"; \
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

USER 1000
ARG SELKIES_WAYLAND=false
ENV PATH=/opt/wine-staging/bin:${PATH} \
    WINELOADER=/opt/wine-staging/bin/wine \
    WINESERVER=/opt/wine-staging/bin/wineserver \
    WINE_PACKAGE_VERSION=${WINE_PACKAGE_VERSION} \
    WINEPREFIX=/home/ubuntu/.wine \
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
      test "$(cat "$WINEPREFIX/.gateway-wine-package-version")" = "$WINE_PACKAGE_VERSION" && \
      test -s "$WINEPREFIX/system.reg" && \
      find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
        -name msedgewebview2.exe -print -quit | grep -q . || \
        { echo "Invalid cached Wine prefix" >&2; exit 1; }; \
    else \
      xvfb-run -a /usr/local/bin/install-client; \
    fi && \
    printf '%s\n' "$WINE_PACKAGE_VERSION" > "$WINEPREFIX/.gateway-wine-package-version"

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
