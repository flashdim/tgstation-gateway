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

## Customize the session

The browser session uses a 1920x1080 display by default. Choose another fixed size with:

```sh
SELKIES_MANUAL_WIDTH=1280 SELKIES_MANUAL_HEIGHT=720 \
  docker compose -f examples/compose.yaml up
```

Set both values to `0` to let the browser control the display size. Change the local web address port with `GATEWAY_PORT`, for example `GATEWAY_PORT=8081`.

## Build locally

To build the image from this repository and use it with Compose:

```sh
docker buildx build --load --platform linux/amd64 -t tgstation-gateway-player .
GATEWAY_IMAGE=tgstation-gateway-player docker compose -f examples/compose.yaml up
```

The image uses checksum-pinned standalone Proton Wine 10.0-4 as its active
runtime. Ubuntu Wine 10 packages supply runtime dependencies; Wine's executable
comes from the Proton archive. Graphics setup runs BYOND's bundled DirectX
installer and verifies its `d3dx9_43.dll` against the bundled CAB. Winetricks
installs DXVK; the resolved DXVK release is not separately version-pinned.

## Important limitations

- This is an early, single-player experiment. Each player needs a separate container; session management, resource limits, and persistent player data are not provided.
- BYOND rendering and gameplay are not fully verified. A successful start does not guarantee that every game or interface will work correctly.
- The example is bound to your local machine. The browser stream is not protected by default; do not expose it directly to the internet. Arrange your own access controls and secure connection if you need remote access.

See the [roadmap](ROADMAP.md) for planned work and known gaps.
