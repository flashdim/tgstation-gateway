# syntax=docker/dockerfile:1
# check=skip=SecretsUsedInArgOrEnv
# SELKIES_ENABLE_BASIC_AUTH is a boolean, not a secret.
# The first milestone is one BYOND client per container, not a session manager.
FROM scratch AS wine-prefix-cache

FROM ghcr.io/selkies-project/selkies/base:2.2.1-ubuntu26.04@sha256:4b70c739ea5aa650dd35a143d92c4bf80b7a527f2c66ee88718b08a5211267ff

USER root
SHELL ["/bin/sh", "-c"]

ARG DEBIAN_FRONTEND=noninteractive
# Native dependencies follow Ubuntu 26.04 libwine Depends/Recommends, not libwine
# itself: Wine also dlopens optional libraries that ldd cannot discover.
RUN selkies-privileged-files release && \
    dpkg --add-architecture i386 && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
      cabextract unzip wget xz-utils openbox trayer fonts-liberation \
      libc6:amd64 libc6:i386 \
      libfontconfig1:amd64 libfontconfig1:i386 \
      libfreetype6:amd64 libfreetype6:i386 \
      libasound2t64:amd64 libasound2t64:i386 \
      libasound2-plugins:amd64 libasound2-plugins:i386 \
      libavcodec62:amd64 libavcodec62:i386 \
      libavformat62:amd64 libavformat62:i386 \
      libavutil60:amd64 libavutil60:i386 \
      libcapi20-3t64:amd64 libcapi20-3t64:i386 \
      libcups2t64:amd64 libcups2t64:i386 \
      libdbus-1-3:amd64 libdbus-1-3:i386 \
      libdrm2:amd64 libdrm2:i386 \
      libdrm-amdgpu1:amd64 libdrm-amdgpu1:i386 \
      libegl1:amd64 libegl1:i386 \
      libgl1:amd64 libgl1:i386 \
      libgl1-mesa-dri:amd64 libgl1-mesa-dri:i386 \
      libglib2.0-0t64:amd64 libglib2.0-0t64:i386 \
      libgnutls30t64:amd64 libgnutls30t64:i386 \
      libgphoto2-6t64:amd64 libgphoto2-6t64:i386 \
      libgphoto2-port12t64:amd64 libgphoto2-port12t64:i386 \
      libgssapi-krb5-2:amd64 libgssapi-krb5-2:i386 \
      libgstreamer-plugins-base1.0-0:amd64 libgstreamer-plugins-base1.0-0:i386 \
      libgstreamer-gl1.0-0:amd64 libgstreamer-gl1.0-0:i386 \
      libgstreamer1.0-0:amd64 libgstreamer1.0-0:i386 \
      gstreamer1.0-plugins-good:amd64 gstreamer1.0-plugins-good:i386 \
      libkrb5-3:amd64 libkrb5-3:i386 \
      libodbc2:amd64 libodbc2:i386 \
      libpcap0.8t64:amd64 libpcap0.8t64:i386 \
      libpcsclite1:amd64 libpcsclite1:i386 \
      libpulse0:amd64 libpulse0:i386 \
      libsane1:amd64 libsane1:i386 \
      libsdl2-2.0-0:amd64 libsdl2-2.0-0:i386 \
      libudev1:amd64 libudev1:i386 \
      libunwind8:amd64 libunwind8:i386 \
      libusb-1.0-0:amd64 libusb-1.0-0:i386 \
      libv4l-0t64:amd64 libv4l-0t64:i386 \
      libvulkan1:amd64 libvulkan1:i386 \
      libwayland-client0:amd64 libwayland-client0:i386 \
      libwayland-egl1:amd64 libwayland-egl1:i386 \
      libx11-6:amd64 libx11-6:i386 \
      libxcomposite1:amd64 libxcomposite1:i386 \
      libxcursor1:amd64 libxcursor1:i386 \
      libxext6:amd64 libxext6:i386 \
      libxfixes3:amd64 libxfixes3:i386 \
      libxi6:amd64 libxi6:i386 \
      libxinerama1:amd64 libxinerama1:i386 \
      libxkbcommon0:amd64 libxkbcommon0:i386 \
      libxkbregistry0:amd64 libxkbregistry0:i386 \
      libxrandr2:amd64 libxrandr2:i386 \
      libxrender1:amd64 libxrender1:i386 \
      libxxf86vm1:amd64 libxxf86vm1:i386 \
      ocl-icd-libopencl1:amd64 ocl-icd-libopencl1:i386 && \
    apt-get clean && rm -rf /var/lib/apt/lists/* && \
    selkies-privileged-files restore

RUN curl -fsSL --retry 3 \
      https://github.com/Kron4ek/Wine-Builds/releases/download/proton-10.0-4/wine-proton-10.0-4-amd64.tar.xz \
      -o /tmp/wine-proton.tar.xz && \
    echo 'ffaf6e766f916a408d273254f6b9c42b1589ac1bb4b02e09ab04650c87bca290  /tmp/wine-proton.tar.xz' | sha256sum -c - && \
    mkdir -p /opt/wine-proton && \
    tar -xJf /tmp/wine-proton.tar.xz --strip-components=1 -C /opt/wine-proton && \
    test -x /opt/wine-proton/bin/wine && \
    test -x /opt/wine-proton/bin/wine-preloader && \
    rm /tmp/wine-proton.tar.xz

# Build-time gate shared by CI and releases. winedmo's old FFmpeg ABI and
# wpcap's libpcap.so.1 are inherited optional gaps; do not fake SONAME links.
RUN set -eu; \
    packages="$(dpkg-query -W -f='${db:Status-Status} ${binary:Package}\n')"; \
    if printf '%s\n' "$packages" | grep -E '^installed (wine(:|$|-|32|64)|libwine)'; then \
      echo "Distro Wine packages must not be installed" >&2; exit 1; \
    fi; \
    test -x /opt/wine-proton/bin/wine-preloader; \
    for architecture in i386 x86_64; do \
      directory="/opt/wine-proton/lib/wine/$architecture-unix"; \
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
      for library in libfreetype.so.6 libfontconfig.so.1 libgnutls.so.30 \
          libgssapi_krb5.so.2 libGL.so.1 libEGL.so.1 libvulkan.so.1; do \
        test -r "/usr/lib/$architecture-linux-gnu/$library"; \
      done; \
    done; \
    for binary in /opt/wine-proton/bin/wine /opt/wine-proton/bin/wineserver; do \
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
ARG BYOND_VERSION=516.1689
ARG BYOND_SHA256=""
ENV BYOND_VERSION=${BYOND_VERSION}

RUN /usr/local/bin/install-byond
RUN xvfb-run -a /usr/local/bin/install-graphics

USER root
RUN install -d -o 1000 -g 1000 /etc/service/byond /etc/service/window-manager /etc/service/byond-tray /home/ubuntu/.config/openbox && \
    install -d -o 1000 -g 1000 -m 1777 /tmp/.X11-unix
COPY --chown=1000:1000 --chmod=755 container/run-client.sh /etc/service/byond/run
COPY --chown=1000:1000 --chmod=755 container/run-window-manager.sh /etc/service/window-manager/run
COPY --chown=1000:1000 --chmod=755 container/run-tray.sh /etc/service/byond-tray/run
COPY --chown=1000:1000 --chmod=644 container/openbox/rc.xml /home/ubuntu/.config/openbox/rc.xml
COPY --chmod=755 container/healthcheck.sh /usr/local/bin/healthcheck
USER 1000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["/usr/local/bin/healthcheck"]
