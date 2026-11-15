# tgstation-gateway

An experimental browser-accessible BYOND client for tgstation. The intended
design is a separate, disposable Wine/BYOND container for each player, with a
session manager. The game server and tgstation-server remain separate.

**Current scope:** a single-player Docker image framework. Session creation,
resource limits and cleanup are not implemented. This is intended for private
self-hosting and is not ready for multi-user deployment.

## Build the player image

The image uses the Selkies desktop image for a headless X11 display, audio and
browser streaming. It installs Wine 11 and uses Winetricks to install Visual
C++ 2022, DirectX components, DXVK and WebView2. It also installs BYOND. It
targets `linux/amd64` and an x64 Wine prefix; this combination has not yet been
validated end to end.

Winetricks downloads Microsoft's WebView2 Evergreen bootstrapper at build time.
The bootstrapper is not checksum-pinned by Winetricks and downloads a current
runtime, so builds are not fully reproducible. Third-party software remains in
the image; check its licensing and redistribution terms before publishing it.

```sh
docker build --platform linux/amd64 -t tgstation-gateway-player .
```

The build downloads the portable Windows BYOND archive from the independently
operated community mirror at `byond-builds.dm-lang.org`, defaulting to version
`516.1688`. To select a version from a shell environment variable, set
`BYOND_VERSION` and pass it as a build argument:

```sh
export BYOND_VERSION=516.1688
docker build --platform linux/amd64 --build-arg BYOND_VERSION \
  -t tgstation-gateway-player .
```

Changing the environment of a running container does not replace the client;
rebuild the image to change versions. You can also pass a trusted checksum with
`--build-arg BYOND_SHA256=<sha256>`. Without it, the download is checked for ZIP
corruption but not against a known digest.

The former `BYOND_DOWNLOAD_BASE_URL` override is no longer supported.

The build requires network access to the community mirror, WineHQ, GitHub,
Microsoft and other Winetricks download hosts. It intentionally fails if an
installer or an integrity check fails. `WINE_PACKAGE_VERSION` is a build
argument if the pinned WineHQ package needs to be changed. Wine initialization
and each Winetricks component log their start and completion and have individual
timeouts. Initial prefix creation suppresses Wine's interactive Mono and Gecko
setup dialogs; the override applies only to initialization, not the running
client.

## CI and releases

GitHub Actions jobs have a 15-minute timeout and use the community BYOND mirror.
Pull requests build the
image and smoke-test the Selkies endpoint and BYOND
pager, without logging in to a game server. Publishing a GitHub release builds
and tests the image again, then pushes it to
`ghcr.io/flashdim/tgstation-gateway` with the release tag. Non-prereleases also
update `latest`. Publishing requires Actions permission to write packages;
check third-party redistribution terms before creating a release.

## Private single-player experiment

The Compose example builds and runs one player container bound to localhost:

```sh
docker compose up --build
```

Set `BYOND_VERSION` (and optionally `BYOND_SHA256`) before building to select a
different BYOND version. Set `GATEWAY_PORT` to change the localhost port.
Rebuild with `docker compose up --build` after changing the BYOND version.
Run `docker compose down` to remove the container and its player data.

Alternatively, run the image built above directly:

```sh
docker run --rm --init --shm-size=2g \
  -p 127.0.0.1:8080:8080 \
  tgstation-gateway-player
```

Open `http://localhost:8080`. The container starts the BYOND pager; sign in
there and connect to your server.
Closing the browser does not automatically remove the container. Stop it with
Ctrl+C. No player data or BYOND login is intended to persist between containers.

Selkies uses WebSockets by default. Software rendering may be too slow for
DXVK; GPU access and hardware-specific configuration require separate testing.
The image exposes a desktop environment, not a hardened application sandbox.
The stream is unprotected by default. Operators are responsible for restricting
access and securing connections outside this project. Do not expose it directly
to the internet or share a container between players.

## Next milestones

Validate login, map rendering, TGUI/WebView2, sound and input against a real
server, then measure per-player memory, CPU/GPU usage and bandwidth. Test two
independent sessions for shared IP and BYOND computer-ID collisions before
designing ban handling. A future manager must enforce isolation, limits and
cleanup; operators remain responsible for access controls.
