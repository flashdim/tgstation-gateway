# tgstation-gateway

<p align="center">
  <a href="https://github.com/flashdim/tgstation-gateway/actions/workflows/ci.yml"><img src="https://github.com/flashdim/tgstation-gateway/actions/workflows/ci.yml/badge.svg?branch=main" alt="Build status"></a><br>
  <img src="https://img.shields.io/badge/Status-mostly%20broken-red?style=flat-square" alt="Status: mostly broken">
  <img src="https://img.shields.io/badge/Gameplay-risky-orange?style=flat-square" alt="Gameplay: risky">
  <img src="https://img.shields.io/badge/Copilot-Robusted-blueviolet?style=flat-square" alt="Copilot: Robusted"><br>
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white" alt="Docker"></a>
  <a href="https://github.com/selkies-project/selkies"><img src="landing/assets/selkies-logo.png" alt="Selkies" height="24"></a>
  <a href="https://www.byond.com/"><img src="landing/assets/byond-logo.png" alt="BYOND" height="24"></a>
  <a href="https://github.com/Kron4ek/Wine-Builds"><img src="https://img.shields.io/badge/Proton%20Wine-10.0--4-722F37?style=flat-square&amp;logo=wine&amp;logoColor=white" alt="Proton Wine 10.0-4"></a>
</p>

The repository currently provides an experimental single-player BYOND image and an optional landing-page prototype. The player streams the screen and audio; it does not host a game server or manage player sessions, and a complete authenticated gameplay session has not been verified.
<img width="1575" height="904" alt="image" src="https://github.com/user-attachments/assets/352d64c5-5ff8-4676-b582-7642ee001f9a" />

## Run the player

You need Docker Compose and an internet connection to download the image. From the repository directory, run:

```sh
docker compose -f examples/compose.yaml pull
docker compose -f examples/compose.yaml up
```

Open [http://localhost:8080](http://localhost:8080) for the player.
The default setup opens the BYOND pager; sign in and choose a server.
If the image is not available from GHCR yet, build it locally as described below.

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

## Test landing page

The optional landing-page prototype runs as a separate localhost-only Compose
service. Build the image locally from the repository root:

```sh
docker build -f landing/Dockerfile -t tgstation-gateway-landing:local .
```

Compose defaults to `ghcr.io/flashdim/tgstation-gateway-landing:latest`.
Before the first release, or to try the latest CI build, select the development
image with `GATEWAY_LANDING_IMAGE=ghcr.io/flashdim/tgstation-gateway-landing:dev`.
To use the image built locally, set
`GATEWAY_LANDING_IMAGE=tgstation-gateway-landing:local`. Then
`docker compose -f examples/compose.yaml --profile landing up` starts the landing
page with the player; without `--profile landing` it is not started. Open [http://localhost:8000](http://localhost:8000), or set
`GATEWAY_LANDING_PORT` to choose another host port.

The landing server validates slot configuration at startup and generates
`slots.js` from an in-memory lifecycle snapshot on each request; no
configuration file is mounted. Compose passes these variables through:

| Variable                 | Default                           | Meaning                                                                        |
| ------------------------ | --------------------------------- | ------------------------------------------------------------------------------ |
| `GATEWAY_PLAY_HOST`      | `localhost:${GATEWAY_PORT:-8080}` | DNS name, with optional port, that serves player sessions                      |
| `GATEWAY_PLAY_SCHEME`    | see below                         | `http` or `https`; defaults to `http` for localhost, else `https`              |
| `GATEWAY_SLOT_COUNT`     | `1`                               | Number of slots, 1–99                                                          |
| `GATEWAY_ACCOUNT_PREFIX` | `LGplayer`                        | Slot accounts are the prefix plus a two-digit number (`LGplayer01`)            |
| `GATEWAY_SLOT_PATH`      | `/`                               | URL path per slot; `{account}` and `{number}` are substituted                  |
| `GATEWAY_DEPLOYMENT_ID`  | `local`                           | Stable deployment identity; use a unique value per deployment on a Docker host |
| `GATEWAY_QUERY_HOST`     | empty                             | Game server DNS name or IPv4 address, as seen by the landing container         |
| `GATEWAY_QUERY_PORT`     | empty                             | Game server BYOND port, 1–65535                                                |

Set both query variables to enable the game status panel. These identify the
DreamDaemon game server, not the player-streaming host in `GATEWAY_PLAY_HOST`
or the TGS API. For example, set `GATEWAY_QUERY_HOST=game.example.org` and
`GATEWAY_QUERY_PORT=1337` in the Compose environment. The landing container
must be able to reach that host and TCP port. `localhost` refers to the landing
container itself, not the Docker host. Leave both empty to disable querying.

The panel polls the tgstation `?status` World Topic using the MIT-licensed
`byond-wire` 0.1.2 client, whose wheel and hash are pinned. The query
does not need BYOND or TGS credentials. A valid response shows the map,
connected clients, round time, and the reported `popcap` (∞ if zero, `?` if
absent).
The cap is tgstation's maximum of its configured soft, hard, and extreme
thresholds, not necessarily a strict connection limit. Time is unavailable
before the round starts. Errors, invalid replies and stale data show
**unavailable**, not offline. A successful response proves only that the
status query answered, not that joining or gameplay works. Compatibility with
the operator's actual game build remains to be verified.

For example, to list two slots at `https://play.lazorgator.party/LGplayer01/`
and `https://play.lazorgator.party/LGplayer02/`:

```sh
GATEWAY_PLAY_HOST=play.lazorgator.party \
GATEWAY_SLOT_COUNT=2 \
GATEWAY_SLOT_PATH='/{account}/' \
GATEWAY_DEPLOYMENT_ID=my-gateway \
docker compose -f examples/compose.yaml --profile landing up
```

With more than one slot, `GATEWAY_SLOT_PATH` must contain `{account}` or
`{number}` so each slot has a distinct link. Prefixes contain 1–24 ASCII letters,
digits, `_` or `-`. Paths permit ASCII letters, digits, `.`, `_`, `~`, `/`, `-`
and the two placeholders; `.` and `..` segments, repeated slashes, percent
encoding, query strings and fragments are rejected. The routing model accepts
only exact generated paths/accounts, rejecting unknown or out-of-range slots.
No client-provided destination or arbitrary upstream is accepted.
The landing page only builds these
links; the operator's reverse proxy must route each path (or host) to the
corresponding player container. The example Compose file runs one player, so
only a single-slot configuration reaches a working player without additional
routing. Invalid values stop the landing container at startup with an error
naming the variable. Startup logs list each generated slot URL.

### Session state and container ownership foundation

`GATEWAY_ACTIVE_SLOTS` is removed, including empty values; remove it from old
deployment configuration. Unallocated slots have `state: null`. The internal
registry reserves a slot as `starting`, then permits `ready`, `reconnect_grace`,
`stopping` and `failed`. Ready sessions can enter reconnect grace and return
to ready. Starting, ready and grace sessions may stop or fail; failed sessions
may enter stopping for cleanup, and stopping may fail. A slot is released only
from stopping or failed, after the future manager confirms container and
session-data cleanup. Snapshots and transitions are serialized within a process.
There are no timers, persistence, readiness probes or orchestration yet: the
standalone landing starts with all slots unallocated, and a restart clears state.

`GATEWAY_DEPLOYMENT_ID` contains 1–64 ASCII letters, digits, `_`, `.` or `-`,
starting with a letter or digit. Keep it stable across manager restarts, unique
on the host, and do not run two managers with the same ID. `local` is only a
single-deployment prototype default. The model defines Docker container labels:

- `io.tgstation-gateway.project=tgstation-gateway`
- `io.tgstation-gateway.deployment=<deployment ID>`
- `io.tgstation-gateway.role=player`
- `io.tgstation-gateway.slot=<two-digit slot number>`
- `io.tgstation-gateway.account=<derived account>`
- `io.tgstation-gateway.session=<canonical UUID>`

The discovery filter uses project, deployment and role. Before any future
adoption, reconciliation or deletion, the ownership predicate additionally
requires a configured account, its matching slot number, and a valid session
UUID. Missing/mismatched labels, other deployments and unknown slots fail
closed. Container names and image names alone never establish ownership.
These are privileged-daemon ownership labels, not player authorization.
This change does not label or manage the standalone Compose player or connect
to Docker. Keep Docker access private to the future manager; labels must never
include keys, credentials or player data.

Exact route lookup is an allowlist, not an authentication boundary. A future
manager must verify trusted session ownership before looking up/routing a slot;
client headers, account names, paths or session UUIDs alone must not grant access.
The external identity/secure-connection integration remains undecided.

The operator must create BYOND accounts manually. For a pager key file obtained
by logging in to the matching account, mount the complete file read-only at
`/run/secrets/LGplayer01_key.txt`, for example, then set `BYOND_KEY_FILE` to
that path. The launcher copies the file unchanged into the disposable Wine
prefix and does not log its contents. Restrict its host permissions while
allowing the player container user to read it. Using this file for login in a
fresh prefix has not yet been verified. Do not put the key or a password in
environment variables, command-line arguments, public configuration, URLs,
images or caches. Rotate the operator-managed source file when the account
key is revoked.
The unallocated link opens its configured URL; ready/grace watch links replace any
existing fragment with `#shared`, preserving the path and query.

Starting, stopping and failed slots are shown without links. The page reads
server-side lifecycle state, but no containers are created, monitored or isolated
because orchestration is not connected. It does not authenticate users or enforce ownership. `#shared` is
not an authorization boundary, and anyone with access to a player URL may
attempt to use it directly. Intended watching by authenticated users and
controller reconnection require trusted identity, ownership and routing
integration ([#48](https://github.com/flashdim/tgstation-gateway/issues/48))
and future session-manager work. Protect both the page and player endpoints
with operator-managed access controls and secure connections; do not expose
the local test server or player stream directly to the internet. See
`landing/assets/ATTRIBUTION.md` for artwork sources and licenses.
The landing image publishes `dev` for main-branch CI builds and `dev-pr<number>`
for same-repository pull requests. Releases publish a version tag matching the
release and `latest` for non-prereleases. CI development tags are pushed before
image validation and may refer to a build that later fails validation.

## Connect directly to a server

To start the client connected to a server instead of opening the pager, provide its address and port:

```sh
BYOND_SERVER=server.example.org:1337 docker compose -f examples/compose.yaml up
```

The key file is optional; without it, BYOND may require
interactive pager login. A BYOND account or server-side authentication may
still be required.
Dream Seeker launches once and remains running. The desktop's **Reset Session**
action restarts it after Selkies clients connect. The BYOND pager path is
unchanged.

## Customize the session

The panel pins only **Reset Session**. Use it to stop BYOND and Wine so the
supervised client can restart. Each service launch first stops the Wine
server for its prefix, then terminates and checks for remaining BYOND and
WebView2 processes owned by the container user. This also covers processes reparented
after a client exits. Cleanup is serialized, and the launcher refuses to
start BYOND if it cannot confirm shutdown. Because the process cleanup is
user-wide rather than prefix-specific, do not run unrelated BYOND or WebView2
sessions as the same user in the player container.

WebView2 runs multiple browser and renderer processes for BYOND's embedded
web interfaces; their presence during a session is expected and disabling
them may break those interfaces. To verify cleanup with a real game, record
the WebView2 PIDs and memory use, reset repeatedly via the shortcut and
browser reconnect, and confirm old PIDs disappear while new interfaces work.
This has not yet been verified in a real gameplay session.

The system tray scales icons with panel height
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

The first-run desktop uses a Plasma slideshow of the images in
`landing/assets/wallpapers/`, including **Glory to Nanotrasen** by **partheosis** and
the **Space Station 13** logo by **Wirewraith**. See `landing/assets/ATTRIBUTION.md` for
sources and licenses (also installed at
`/usr/share/tgstation-gateway/wallpaper-attribution.md` in the image).
Images are centered at their original size against a black background. This
first-run default applies to fresh containers; existing Plasma settings are not
overwritten. Plasma's default slide interval is 15 minutes. To add
images to the built-in collection, place them in `landing/assets/wallpapers/`, record
their attribution and license, and rebuild the image.

To replace the collection without rebuilding, bind-mount an operator-supplied
directory of images read-only at `/usr/share/tgstation-gateway/wallpapers`
before starting a fresh container.
For example, add this under the Compose player's `volumes`:

```yaml
- /absolute/path/to/wallpapers:/usr/share/tgstation-gateway/wallpapers:ro
```

### Desktop verification

The layout and panel properties were queried in fresh **desktop-only** test
containers based on the pinned Selkies image, in both X11 and Wayland.
Screenshots, the wallpaper slideshow, and the BYOND window's geometry and
usability while the panel dodges windows have **not** been manually
verified in the complete player image. To verify, start a fresh container in
each display mode, capture the desktop and panel before and while an
application window overlaps the panel, verify that the slideshow changes
images, then connect to a test server and
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

At runtime, all Wine debug channels (including errors) are disabled with
`WINEDEBUG=-all`. Selkies logs and launcher error messages remain visible.
Build-time Wine errors are still logged.

## Important limitations

- This is an early, single-player experiment. Each player needs a separate container; session management, resource limits, and persistent player data are not provided.
- BYOND rendering and gameplay are not fully verified. A successful start does not guarantee that every game or interface will work correctly.
- The example is bound to your local machine. The browser stream is not protected by default; do not expose it directly to the internet. Arrange your own access controls and secure connection if you need remote access.

See the [roadmap](ROADMAP.md) for planned work and known gaps.
