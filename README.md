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
To test the published development image explicitly in Wayland mode, run:

```sh
GATEWAY_IMAGE=ghcr.io/flashdim/tgstation-gateway:dev SELKIES_WAYLAND=true \
  docker compose -f examples/compose.yaml up --pull always
```

Press **Ctrl+C** to stop the running container. To remove it and its temporary player data, run:

```sh
docker compose -f examples/compose.yaml down
```

## Connect directly to a server

To start the client connected to a server instead of opening the pager, provide its address and port:

```sh
BYOND_SERVER=server.example.org:1337 docker compose -f examples/compose.yaml up
```

A BYOND account or server-side authentication may still be required.
On the first direct-server launch in each container, Dream Seeker opens once
and the gateway tries to close it normally before launching the regular
session. If Dream Seeker is still running 15 seconds after launch, the gateway
force-stops the BYOND processes and the session's Wine server before
relaunching. The user verified that this startup cycle achieves the corrected
DPI goal in their setup. The BYOND pager path is unchanged; this result does
not establish general rendering or gameplay compatibility.

## Customize the session

KWin maximizes the LazorGator Party game window without entering true
fullscreen. The rule does not apply to the BYOND pager or other window
titles.

Fresh Plasma sessions use Breeze Dark colors, a dark Plasma theme, Breeze
window decorations, dark icons and Breeze cursors. The bottom panel is
centered, fits its contents, auto-hides, is opaque and non-floating, and is
64 pixels high. Its icons-only task manager pins Dolphin and System Monitor.
These are first-run defaults: changes made in Plasma remain in the session's
user configuration, which is discarded with the container.

The defaults are installed in `/etc/xdg/kdeglobals`, `/etc/xdg/plasmarc`
and `/etc/xdg/kcminputrc`. The first-run panel and wallpaper layout is
`/usr/share/plasma/look-and-feel/org.kde.breezedark.desktop/contents/layouts/org.kde.plasma.desktop-layout.js`;
the game window rule is `/etc/xdg/kwinrulesrc`. Operators can mount
replacement configuration files read-only before starting a fresh container,
or change the appearance and panel in Plasma. If selecting a different global
look-and-feel, its own first-run layout may replace the gateway panel layout.

The default wallpaper is KDE's **Sub-Arctic** by Krystian Zajdel, provided
by the base image under [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/);
its metadata is at `/usr/share/wallpapers/Next/metadata.json`. To override it
without rebuilding, bind-mount an operator-supplied PNG read-only at
`/usr/share/tgstation-gateway/wallpaper.png` before starting the container.
For example, add this under the Compose player's `volumes`:

```yaml
- /absolute/path/to/wallpaper.png:/usr/share/tgstation-gateway/wallpaper.png:ro
```

The requested [Glory to Nanotrasen artwork](https://www.deviantart.com/partheosis/art/Glory-to-Nanotrasen-547539107)
by partheosis is not included: its redistribution license could not be
verified. Operators must verify permission and applicable terms before using
or distributing their own copy.

### Desktop verification

The layout and panel properties were queried in fresh **desktop-only** test
containers based on the pinned Selkies image, in both X11 and Wayland.
Screenshots, the requested wallpaper, and the BYOND window's maximized
geometry and usability with the hidden panel have **not** been manually
verified in the complete player image. To verify, start a fresh container in
each display mode, capture the desktop and panel before and after hovering
at the bottom edge, then connect to a test server and capture the maximized
game window with the panel hidden. Record the image digest, display mode,
screenshots and any failures separately from startup or health checks.

Selkies follows the browser's display size by default. To use a fixed size:

```sh
SELKIES_MANUAL_WIDTH=1280 SELKIES_MANUAL_HEIGHT=720 \
  docker compose -f examples/compose.yaml up
```

Change the local web address port with `GATEWAY_PORT`, for example `GATEWAY_PORT=8081`.

## Build locally

To build the image from this repository and use it with Compose:

```sh
docker buildx build --load --platform linux/amd64 -t tgstation-gateway-player .
GATEWAY_IMAGE=tgstation-gateway-player docker compose -f examples/compose.yaml up
```

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
