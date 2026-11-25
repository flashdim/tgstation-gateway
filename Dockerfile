# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
FROM scratch AS wine-prefix-cache
FROM scratch AS wine-download-cache

# Latest Ubuntu 26.04 Plasma image as of 2026-11-19 (Selkies 2.2.1).
FROM ghcr.io/selkies-project/selkies-egl-desktop:26.04@sha256:cee92447ae1445c0af4c26a73e32caa7d7cf31aed51b5c5e6549d94cc8fa8c9e

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
ARG WINE_PACKAGE_VERSION=10.0~repack-12ubuntu1
ARG WINE_PROTON_VERSION=10.0-4

RUN set -eu; \
    selkies-privileged-files release; \
    dpkg --add-architecture i386; \
    rm -f /etc/apt/sources.list.d/steam-stable.list /etc/apt/sources.list.d/steam-beta.list; \
    apt-get update; \
    removable_packages="$(dpkg-query -W -f='${db:Status-Status} ${binary:Package}\n' | \
      awk '$1 == "installed" && ($2 ~ /^(steam-launcher|heroic|lutris|firefox|google-chrome-stable|transmission-qt|kget|kdeconnect|kwrite|kate|kinfocenter|kmenuedit|kmouth|kmag|ktimer|kmousetool|kcharselect|kde-spectacle|kfind|konsole|ark|filelight|okular|sweeper|vlc|plasma-discover|dolphin|kdf|ksystemlog|kcalc|gwenview|vim|systemsettings|plasma-systemmonitor)$/ || $2 ~ /^libreoffice/) { print $2 }')"; \
    if [ -n "$removable_packages" ]; then \
      apt-get remove -y $removable_packages; \
    fi; \
    apt-mark hold kwin-addons kwin-common kwin-data kwin-wayland libkwin6; \
    apt-get dist-upgrade -y --no-remove; \
    apt-get install -y --no-install-recommends \
      "wine=$WINE_PACKAGE_VERSION" "wine32:i386=$WINE_PACKAGE_VERSION" \
      "wine64=$WINE_PACKAGE_VERSION" cabextract unzip wget xz-utils \
      fonts-liberation libfreetype6:i386 libfontconfig1:i386 \
      libgnutls30t64:i386 libgssapi-krb5-2:i386 libvulkan1:i386; \
    apt-get autoremove -y; \
    apt-get clean; rm -rf /var/lib/apt/lists/*; \
    selkies-privileged-files restore

COPY container/download-wine.sh container/wine-proton.env /tmp/wine-download/
RUN --mount=type=bind,from=wine-download-cache,target=/tmp/wine-download-cache \
    set -eu; \
    if [ -f /tmp/wine-download-cache/wine-proton.tar.xz ]; then \
      cp /tmp/wine-download-cache/wine-proton.tar.xz /tmp/wine-proton.tar.xz; \
    fi; \
    build_version="$WINE_PROTON_VERSION"; \
    . /tmp/wine-download/wine-proton.env; \
    test "$build_version" = "$WINE_PROTON_VERSION"; \
    sh /tmp/wine-download/download-wine.sh /tmp; \
    mkdir -p /opt/wine-proton; \
    tar -xJf /tmp/wine-proton.tar.xz --strip-components=1 -C /opt/wine-proton; \
    test -x /opt/wine-proton/bin/wine; \
    test -x /opt/wine-proton/bin/wine-preloader; \
    rm /tmp/wine-proton.tar.xz

# Build-time gate shared by CI and releases. Do not fake SONAME links.
RUN set -eu; \
    for package in wine wine32:i386 wine64; do \
      test "$(dpkg-query -W -f='${Version}' "$package")" = "$WINE_PACKAGE_VERSION"; \
    done; \
    test -x /opt/wine-proton/bin/wine; \
    test -x /opt/wine-proton/bin/wine-preloader; \
    for architecture in i386 x86_64; do \
      directory="/opt/wine-proton/lib/wine/$architecture-unix"; \
      for library in libfreetype.so.6 libfontconfig.so.1 libgnutls.so.30 \
          libgssapi_krb5.so.2 libGL.so.1 libEGL.so.1 libvulkan.so.1; do \
        test -r "/usr/lib/$architecture-linux-gnu/$library" || \
          { echo "Missing or unreadable /usr/lib/$architecture-linux-gnu/$library" >&2; exit 1; }; \
      done; \
      test -d "$directory" || { echo "Missing $architecture Unix modules" >&2; exit 1; }; \
      for module in ntdll.so win32u.so winex11.so winewayland.so \
          winealsa.so winepulse.so winevulkan.so; do \
        test -r "$directory/$module" || \
          { echo "Missing $directory/$module" >&2; exit 1; }; \
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
    for binary in /opt/wine-proton/bin/wine /opt/wine-proton/bin/wineserver; do \
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
ARG SELKIES_WAYLAND=true
ENV PATH=/opt/wine-proton/bin:${PATH} \
    WINELOADER=/opt/wine-proton/bin/wine \
    WINESERVER=/opt/wine-proton/bin/wineserver \
    WINE_PACKAGE_VERSION=${WINE_PACKAGE_VERSION} \
    WINE_PROTON_VERSION=${WINE_PROTON_VERSION} \
    WINEPREFIX=/home/ubuntu/.wine \
    WINEARCH=win64 \
    SELKIES_WAYLAND=${SELKIES_WAYLAND} \
    SELKIES_WAYLAND_X11_FALLBACK=false \
    SELKIES_ENABLE_HTTPS=false \
    SELKIES_ENABLE_BASIC_AUTH=false \
    SELKIES_COMMAND_ENABLED=false \
    SELKIES_RUN_AFTER_CONNECT=/usr/local/bin/reset-session \
    SELKIES_MODE=websockets \
    SELKIES_FRAMERATE=60 \
    SELKIES_UI_SIDEBAR_SHOW_SCREEN_SETTINGS=false \
    SELKIES_UI_SIDEBAR_SHOW_AUDIO_SETTINGS=false \
    SELKIES_FILE_TRANSFERS=none \
    SELKIES_PRINTING_ENABLED=false \
    SELKIES_UI_TITLE="LazorGator Party" \
    SELKIES_UI_SHOW_LOGO=false \
    SELKIES_UI_SHOW_CORE_BUTTONS=false \
    SELKIES_UI_SIDEBAR_SHOW_FILES=false \
    SELKIES_UI_SIDEBAR_SHOW_APPS=false \
    SELKIES_UI_SIDEBAR_SHOW_GAMEPADS=false \
    SELKIES_UI_SIDEBAR_SHOW_WEBCAM=false \
    SELKIES_UI_SIDEBAR_SHOW_GAMING_MODE=false \
    SELKIES_UI_SIDEBAR_SHOW_TRACKPAD=false \
    SELKIES_UI_SIDEBAR_SHOW_SOFT_BUTTONS=false

RUN --mount=type=bind,from=wine-prefix-cache,target=/tmp/wine-prefix-cache \
    if [ -f /tmp/wine-prefix-cache/prefix.tar.gz ]; then \
      mkdir -p "$WINEPREFIX" && \
      tar -xzf /tmp/wine-prefix-cache/prefix.tar.gz -C "$WINEPREFIX" && \
      test "$(cat "$WINEPREFIX/.gateway-proton-version")" = "$WINE_PROTON_VERSION" && \
      test -s "$WINEPREFIX/system.reg" && \
      find "$WINEPREFIX/drive_c/Program Files (x86)/Microsoft/EdgeWebView/Application" \
        -name msedgewebview2.exe -print -quit | grep -q . || \
        { echo "Invalid cached Wine prefix" >&2; exit 1; }; \
    else \
      xvfb-run -a /usr/local/bin/install-client; \
    fi && \
    printf '%s\n' "$WINE_PROTON_VERSION" > "$WINEPREFIX/.gateway-proton-version"

COPY --chmod=755 container/install-byond.sh /usr/local/bin/install-byond
COPY --chmod=755 container/install-graphics.sh /usr/local/bin/install-graphics
ARG BYOND_VERSION=516.1689
ARG BYOND_SHA256=""
ENV BYOND_VERSION=${BYOND_VERSION}

RUN /usr/local/bin/install-byond
RUN xvfb-run -a /usr/local/bin/install-graphics

USER root
RUN install -d -o 1000 -g 1000 /etc/service/byond && \
    install -d -o 1000 -g 1000 /home/ubuntu/.local/share && \
    install -d -o 1000 -g 1000 -m 1777 /tmp/.X11-unix
COPY --chown=1000:1000 --chmod=755 container/run-client.sh /etc/service/byond/run
COPY --chmod=755 container/publish-xwayland-env.sh /usr/local/bin/publish-xwayland-env
COPY --chmod=644 container/byond-xwayland.desktop /etc/xdg/autostart/byond-xwayland.desktop
COPY --chmod=755 container/configure-plasma.sh /usr/local/bin/configure-plasma
COPY --chmod=644 container/plasma-layout.js /usr/local/share/plasma-layout.js
COPY --chmod=644 container/reset-session.desktop /usr/share/applications/reset-session.desktop
COPY --chmod=755 container/reset-session.sh /usr/local/bin/reset-session
COPY --chmod=644 container/configure-plasma.desktop /etc/xdg/autostart/configure-plasma.desktop
COPY --chmod=644 container/plasma-default-layout.js /usr/share/plasma/look-and-feel/org.kde.breezedark.desktop/contents/layouts/org.kde.plasma.desktop-layout.js
RUN set -eu; \
    kwriteconfig6 --file /etc/xdg/kdeglobals --group KDE --key LookAndFeelPackage org.kde.breezedark.desktop; \
    kwriteconfig6 --file /etc/xdg/kdeglobals --group General --key ColorScheme BreezeDark; \
    kwriteconfig6 --file /etc/xdg/kdeglobals --group Icons --key Theme breeze-dark; \
    kwriteconfig6 --file /etc/xdg/plasmarc --group Theme --key name breeze-dark; \
    kwriteconfig6 --file /etc/xdg/kcminputrc --group Mouse --key cursorTheme breeze_cursors; \
    chown root:root /etc/xdg/kdeglobals /etc/xdg/plasmarc /etc/xdg/kcminputrc; \
    chmod 644 /etc/xdg/kdeglobals /etc/xdg/plasmarc /etc/xdg/kcminputrc; \
    install -d -o root -g root -m 755 /usr/share/tgstation-gateway/wallpapers
COPY --chmod=644 landing/assets/wallpapers/ /usr/share/tgstation-gateway/wallpapers/
COPY --chmod=644 landing/assets/ATTRIBUTION.md /usr/share/tgstation-gateway/wallpaper-attribution.md
COPY --chmod=755 container/healthcheck.sh /usr/local/bin/healthcheck
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck"]
