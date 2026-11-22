# tgstation-gateway

<p align="center">
  <a href="https://github.com/flashdim/tgstation-gateway/actions/workflows/ci.yml"><img src="https://github.com/flashdim/tgstation-gateway/actions/workflows/ci.yml/badge.svg?branch=main" alt="Build status"></a><br>
  <img src="https://img.shields.io/badge/Status-mostly%20broken-red?style=flat-square" alt="Status: mostly broken">
  <img src="https://img.shields.io/badge/Gameplay-risky-orange?style=flat-square" alt="Gameplay: risky">
  <img src="https://img.shields.io/badge/Copilot-Robusted-blueviolet?style=flat-square" alt="Copilot: Robusted"><br>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white" alt="Docker"></a>
  <a href="https://github.com/selkies-project/selkies"><img src="assets/selkies-logo.png" alt="Selkies" height="24"></a>
  <a href="https://www.byond.com/"><img src="assets/byond-logo.png" alt="BYOND" height="24"></a>
  <a href="https://github.com/Kron4ek/Wine-Builds"><img src="https://img.shields.io/badge/Proton%20Wine-10.0--4-722F37?style=flat-square&amp;logo=wine&amp;logoColor=white" alt="Proton Wine 10.0-4"></a>
</p>

Run the BYOND player in your browser without installing BYOND on your computer. This experimental project streams the player's screen and audio; it does not host a game server.
<img width="1575" height="904" alt="image" src="https://github.com/user-attachments/assets/352d64c5-5ff8-4676-b582-7642ee001f9a" />

## Start playing

You need Docker Compose and an internet connection to download the image. From the repository directory, run:

```sh
docker compose -f examples/compose.yaml pull
docker compose -f examples/compose.yaml up
```

Open [http://localhost:8080](http://localhost:8080). The default setup opens the BYOND pager; sign in and choose a server. If the image is not available from GHCR yet, build it locally as described below.

The image uses Selkies' EGL KDE Plasma desktop with KWin on Wayland by
default. Set `SELKIES_WAYLAND=false` when running Compose to compare with
Plasma on X11/Xvfb.
In Wayland mode, BYOND starts once Plasma shares its authenticated XWayland
display with the gateway's launcher.
Compose disables gamepad, microphone, and webcam forwarding by default. It
selects H.264 and allows Selkies to use an available GPU for rendering and
encoding; the GPU Compose override passes through `/dev/dri`. The container
does not receive Bluetooth hardware or the host system bus, so Bluetooth is
unavailable in this setup.
To test the published development image explicitly in Wayland mode, run:

```sh
GATEWAY_IMAGE=ghcr.io/flashdim/tgstation-gateway:dev SELKIES_WAYLAND=true \
  docker compose -f examples/compose.yaml up --pull always
```

Press **Ctrl+C** to stop the running container. To remove it and its temporary player data, run:

```sh
docker compose -f examples/compose.yaml down
```

The Compose example mounts the host's `/etc/localtime` read-only so the
container uses the host's date, time and timezone. Set `TZ` (for example
`TZ=Europe/Berlin`) to override the timezone. On hosts without
`/etc/localtime`, remove that volume and set `TZ`.

## Connect directly to a server

To start the client connected to a server instead of opening the pager, provide its address and port:

```sh
BYOND_SERVER=server.example.org:1337 docker compose -f examples/compose.yaml up
```

A BYOND account or server-side authentication may still be required.
Dream Seeker launches once and remains running. The desktop's **Reset Session**
action restarts it after Selkies clients connect. The BYOND pager path is
unchanged.

## Customize the session

The panel pins only **Reset Session**. Use it to stop BYOND and Wine so the
supervised client can restart. The system tray scales icons with panel height
and always shows audio volume. Clipboard, Camera Indicator, Disks & Devices,
Keyboard Layout, Lock Keys Status, Disk Quota, Input Method, Media Player,
Notifications, Trashcan, and Weather Report are disabled. The digital clock is
also present in the panel. Tray preferences are applied to the Plasma 6 system
tray containment at login.

Fresh Plasma sessions use Breeze Dark colors, a dark Plasma theme, Breeze
window decorations, dark icons and Breeze cursors. The bottom panel is
centered, fits its contents, dodges application windows, is opaque and
non-floating, and is 64 pixels high. Its task manager displays window labels
with icons and pins Reset Session. These are first-run defaults; the shortcut
and tray settings are reapplied at login.
Other changes made in Plasma remain in the session's user configuration,
which is discarded with the container.

The defaults are installed in `/etc/xdg/kdeglobals`, `/etc/xdg/plasmarc`
and `/etc/xdg/kcminputrc`. The first-run panel and wallpaper layout is
`/usr/share/plasma/look-and-feel/org.kde.breezedark.desktop/contents/layouts/org.kde.plasma.desktop-layout.js`.
Operators can mount
replacement configuration files read-only before starting a fresh container,
or change the appearance and panel in Plasma. If selecting a different global
look-and-feel, its own first-run layout may replace the gateway panel layout.

The default wallpaper is [**Glory to Nanotrasen**](https://www.deviantart.com/partheosis/art/Glory-to-Nanotrasen-547539107)
by **partheosis**, used under [CC BY-NC 3.0](https://creativecommons.org/licenses/by-nc/3.0/),
as indicated by the source URL. The repository copy and attribution record are
at `assets/glory-to-nanotrasen.jpg` and `assets/ATTRIBUTION.md`.

To override the wallpaper without rebuilding, bind-mount an operator-supplied
image read-only at `/usr/share/tgstation-gateway/wallpaper.jpg` before starting
the container.
For example, add this under the Compose player's `volumes`:

```yaml
- /absolute/path/to/wallpaper.jpg:/usr/share/tgstation-gateway/wallpaper.jpg:ro
```

### Desktop verification

The layout and panel properties were queried in fresh **desktop-only** test
containers based on the pinned Selkies image, in both X11 and Wayland.
Screenshots, the requested wallpaper, and the BYOND window's geometry and
usability while the panel dodges windows have **not** been manually
verified in the complete player image. To verify, start a fresh container in
each display mode, capture the desktop and panel before and while an
application window overlaps the panel, then connect to a test server and
capture the game window with the panel dodging it. Record the image digest,
display mode, screenshots and any failures separately from startup or health
checks.

Selkies follows the browser's display size by default. Common stream and
display settings can be overridden with `SELKIES_MODE` (default `webrtc`),
`SELKIES_FRAMERATE` (default `60`),
`SELKIES_VIDEO_BITRATE`, `SELKIES_AUDIO_BITRATE`, `SELKIES_ENABLE_RESIZE`, and
`SELKIES_SCALING_DPI`. To use a fixed size:

```sh
SELKIES_MANUAL_WIDTH=1280 SELKIES_MANUAL_HEIGHT=720 \
  docker compose -f examples/compose.yaml up
```

The Selkies interface title and sidebar controls can be overridden with the
`SELKIES_UI_*` settings in `examples/compose.yaml`. File transfers and printing
default to disabled (`SELKIES_FILE_TRANSFERS=none` and
`SELKIES_PRINTING_ENABLED=false`).

Change the local web address port with `GATEWAY_PORT`, for example `GATEWAY_PORT=8081`.

## Build locally

To build the image from this repository and use it with Compose:

```sh
docker buildx build --load --platform linux/amd64 -t tgstation-gateway-player .
GATEWAY_IMAGE=tgstation-gateway-player docker compose -f examples/compose.yaml up
```

The package layer upgrades available OS packages, removes selected applications
and unneeded dependencies, and installs the pinned Wine packages. The upgrade
fails if it would need to remove packages; the Wine pins must remain available
in the Ubuntu repositories. Package versions depend on repository state at
build time. Use `--no-cache` when rebuilding to refresh the package layer;
Docker may otherwise reuse an older layer.
The Selkies-patched KWin packages are held at the base image's versions to
preserve its Wayland compositor; dependent packages may also be kept back.
Update the pinned base image to refresh them.
The unused Steam apt sources are removed with the Steam launcher.

The image uses checksum-pinned standalone Proton Wine 10.0-4 as its active
runtime. Ubuntu Wine 10 packages supply runtime dependencies; Wine's executable
comes from the Proton archive. Graphics setup runs BYOND's bundled DirectX
installer and verifies its `d3dx9_43.dll` against the bundled CAB. Graphics
setup also installs checksum-verified DXVK 3.1.1.

## Important limitations

- This is an early, single-player experiment. Each player needs a separate container; session management, resource limits, and persistent player data are not provided.
- BYOND rendering and gameplay are not fully verified. A successful start does not guarantee that every game or interface will work correctly.
- The example is bound to your local machine. The browser stream is not protected by default; do not expose it directly to the internet. Arrange your own access controls and secure connection if you need remote access.

See the [roadmap](ROADMAP.md) for planned work and known gaps.
