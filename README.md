# tgstation-gateway

An experimental browser-accessible BYOND client for tgstation. The intended
design is a separate, disposable Wine/BYOND container for each player, with a
session manager and Traefik handling access. The game server and
tgstation-server remain separate.

**Current scope:** a single-player Docker image framework. Session creation,
Traefik integration, session ownership checks, resource limits and cleanup
are not implemented. This is not ready for public or multi-user deployment.

## Build the player image

The image uses the Selkies desktop image for a headless X11 display, audio and
browser streaming. It installs Wine 11, Visual C++ 2022, DirectX components,
DXVK and the supplied BYOND and WebView2 installers. It targets `linux/amd64`
and an x64 Wine prefix; this combination has not yet been validated end to end.

Download the [Windows BYOND installer](https://www.byond.com/download/)
matching your game server and Microsoft's
[**x64 WebView2 Evergreen standalone installer**](https://developer.microsoft.com/en-us/microsoft-edge/webview2/)
from their official sources.
Check the licensing terms for your intended use. Place them in this directory
as `installers/byond.exe` and `installers/webview2-x64.exe`; do not commit them.
BuildKit mounts these files during installation rather than copying the
installers into an image layer. The installed software is still present in the
image and its redistribution terms must be checked before publishing it.

```sh
docker build --platform linux/amd64 -t tgstation-gateway-player .
```

The build requires network access to WineHQ, GitHub, Microsoft and other
Winetricks download hosts. It intentionally fails if an installer or an
integrity check fails. `WINE_PACKAGE_VERSION` is a build argument if the pinned
WineHQ package needs to be changed.

## Private single-player experiment

Set a unique password in your shell without putting it in the command history,
then run the image bound only to localhost:

```sh
read -rs SELKIES_BASIC_AUTH_PASSWORD; echo
export SELKIES_BASIC_AUTH_PASSWORD
docker run --rm --init --shm-size=2g \
  -p 127.0.0.1:8080:8080 \
  -e SELKIES_BASIC_AUTH_USER=player \
  -e SELKIES_BASIC_AUTH_PASSWORD \
  tgstation-gateway-player
```

Open `https://localhost:8080` and accept the self-signed certificate. The
container starts the BYOND pager; sign in there and connect to your server.
Closing the browser does not automatically remove the container. Stop it with
Ctrl+C. No player data or BYOND login is intended to persist between containers.

Selkies uses WebSockets by default. Software rendering may be too slow for
DXVK; GPU access and hardware-specific configuration require separate testing.
The image exposes a desktop environment, not a hardened application sandbox.
Do not expose it directly to the internet or share a container between players.
Traefik authentication must not be mistaken for per-session authorization.

## Next milestones

Validate login, map rendering, TGUI/WebView2, sound and input against a real
server, then measure per-player memory, CPU/GPU usage and bandwidth. Test two
independent sessions for shared IP and BYOND computer-ID collisions before
designing ban handling. A future manager must authorize session ownership,
including streaming connections, and enforce isolation, limits and cleanup.
