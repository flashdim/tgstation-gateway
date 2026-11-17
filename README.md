# tgstation-gateway

<p align="center">
  <a href="https://github.com/flashdim/tgstation-gateway/actions/workflows/ci.yml"><img src="https://github.com/flashdim/tgstation-gateway/actions/workflows/ci.yml/badge.svg?branch=main" alt="Build status"></a>
  <img src="https://img.shields.io/badge/Status-mostly%20broken-red?style=flat-square" alt="Status: mostly broken">
  <img src="https://img.shields.io/badge/Gameplay-risky-orange?style=flat-square" alt="Gameplay: risky">
  <img src="https://img.shields.io/badge/Copilot-Robusted-blueviolet?style=flat-square" alt="Copilot: Robusted">
  <a href="https://www.docker.com/"><img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&amp;logo=docker&amp;logoColor=white" alt="Docker"></a>
  <a href="https://github.com/selkies-project/selkies"><img src="https://img.shields.io/badge/Selkies-desktop%20streaming-0A7EA4?style=flat-square" alt="Selkies desktop streaming"></a>
  <a href="https://www.byond.com/"><img src="https://img.shields.io/badge/BYOND-game%20client-6D52A3?style=flat-square" alt="BYOND game client"></a>
</p>

An experimental browser-accessible BYOND client for tgstation. The intended
design is a separate, disposable Wine/BYOND container for each player, with a
session manager. The game server and tgstation-server remain separate.

**Current scope:** a single-player Docker image framework. Session creation,
resource limits and cleanup are not implemented. This is intended for private
self-hosting and is not ready for multi-user deployment.

See [ROADMAP.md](ROADMAP.md) for milestones and acceptance criteria.

## Build the player image

The image uses the Selkies base for a headless X11 display, audio and browser
streaming, with Openbox managing BYOND windows instead of a desktop. It uses
Kron4ek's checksum-verified standalone Proton-based Wine 10.0-4 amd64 build as
the Wine runtime, and Winetricks to install Visual C++ 2022, DirectX components,
core fonts, RichEdit and WebView2. Ubuntu's pinned `wine`, `wine32:i386` and
`wine64` packages supply runtime dependencies, with explicit supplemental
32-bit font, TLS/Kerberos and Vulkan libraries. This restores the earlier
package-based setup instead of maintaining the complete native library list.
Proton remains the active runtime through `/opt/wine-proton/bin` at the front
of PATH; its archive and checksum are unchanged. Libraries loaded with `dlopen`
are not all visible to `ldd`; package installation and dependency checks alone
do not establish compatibility.
The pinned Selkies base already supplies Mesa Vulkan ICDs for both architectures;
this is not just a Vulkan-loader-only setup.

Every image build, including releases, checks both loader architectures,
core display/audio/GStreamer modules and
selected dynamically loaded libraries before creating the prefix. This is not
a gameplay or WebView compatibility test. The pinned standalone runtime's
optional `winedmo.so` expects FFmpeg SONAMEs `libavcodec.so.58`,
`libavformat.so.58` and `libavutil.so.56`, unavailable in Ubuntu 26.04.
Its optional packet-capture module `wpcap.so` expects `libpcap.so.1`, whereas
Ubuntu's native library exposes `libpcap.so.0.8`. Both gaps affect both
architectures; installing Ubuntu Wine would not supply those SONAMEs either.
The build checks intentionally exclude these optional modules; current Ubuntu
libraries do not resolve the inherited gaps, and no compatibility symlinks
are installed.

The Proton 10.0-4 amd64 archive checksum is pinned for the runtime comparison.
A user-reported test of Proton 11.0-2 without Ubuntu Wine packages showed no
major change, though the UI looked cleaner and closer to a local environment.
The latest CI run built and published the image after a retry, passed the X11
and Wayland startup smoke tests, and passed the Wine runtime check. The first
attempt stopped during core-font registration after Wine reported a connection
reset; this did not recur on retry. Startup checks do not establish gameplay or
WebView compatibility. The Proton archive includes `winegstreamer.so` for
amd64 but not i386; the build checks the module where present and does not claim
32-bit GStreamer-backed media compatibility.
It also installs BYOND. It targets `linux/amd64` and an x64 Wine prefix. It
installs BYOND's bundled DirectX setup, native `d3dx9_43` and DXVK 2.7.1,
which requires a Vulkan 1.3-capable driver.
See the community
[Wine-Byond-help guide](https://github.com/kinggoldcatter/Wine-Byond-help) for
BYOND-specific Wine troubleshooting.

The BYOND service removes Selkies' `LD_PRELOAD` input and webcam interposers
from Wine's environment: testing showed that removing them lets the VC runtime
installer complete and restored BYOND game and stat-panel rendering in that
test environment. A later user-reported session rendered the menu, dialogs and
audio, but showed a black game scene with a few solid-color tiles after joining,
with and without GPU access under Wine Staging. Ubuntu Wine 10 rendered the
scene but failed to load fancy chat and the stat panel. In a separate container,
a fresh prefix using standalone Proton-based Wine 11.0-2, BYOND's bundled
DirectX setup and DXVK 2.7.1 rendered the scene and loaded those panels, but
showed two extra blank dialogs under Wayland/XWayland; [issue #4](https://github.com/flashdim/tgstation-gateway/issues/4)
tracks the investigation. The user now reports that the extra windows appear
briefly at startup and disappear after connecting, and that restoring Ubuntu
Wine packages as runtime dependencies caused no major rendering issues. No
root cause or automated window suppression was established. These reports do
not verify complete gameplay, map rendering or WebView compatibility. Wine
applications do not receive Selkies' injected gamepad or webcam integrations.

Winetricks downloads Microsoft's WebView2 Evergreen bootstrapper at build time.
The bootstrapper is not checksum-pinned by Winetricks and downloads a current
runtime, so builds are not fully reproducible. Third-party software remains in
the image; check its licensing and redistribution terms before publishing it.

Building requires Docker with BuildKit and the Buildx CLI plugin; the classic
builder cannot build this Dockerfile. The Compose example pulls a published
image instead and requires the Docker Compose plugin. Check the installed tools
with:

```sh
docker buildx version
docker compose version
```

If Buildx is missing, install it using the packages for your Docker
installation. For example, on Ubuntu or Debian with
[Docker's package repository](https://docs.docker.com/engine/install/), install
`docker-buildx-plugin` with `sudo apt-get install docker-buildx-plugin`.
On an up-to-date Arch Linux system, install it with
`sudo pacman -S docker-buildx`. Package names may differ for other
distribution-provided Docker installations.
Ensure `DOCKER_BUILDKIT` is not set to `0`; installing Buildx is still
required if the plugin is missing.

```sh
docker build --platform linux/amd64 -t tgstation-gateway-player .
```

The build downloads the portable Windows BYOND archive from the independently
operated community mirror at `byond-builds.dm-lang.org`, defaulting to version
`516.1689`. The archive must include BYOND's bundled DirectX setup and June 2010
`d3dx9_43` CAB. To select a version from a shell environment variable, set
`BYOND_VERSION` and pass it as a build argument:

```sh
export BYOND_VERSION=516.1689
docker build --platform linux/amd64 --build-arg BYOND_VERSION \
  -t tgstation-gateway-player .
```

Changing the environment of a running container does not replace the client;
rebuild the image to change versions. You can also pass a trusted checksum with
`--build-arg BYOND_SHA256=<sha256>`. Without it, the download is checked for ZIP
corruption but not against a known digest.
Version 516.1689 has not yet been verified against the community mirror or in
gameplay: DNS resolution for the mirror was unavailable in the test environment.

The former `BYOND_DOWNLOAD_BASE_URL` override is no longer supported.

The build requires network access to the community mirror, Ubuntu, GitHub,
Microsoft and other Winetricks download hosts. The RichEdit verbs download large
Windows service packs and legacy installers from third-party and archive
mirrors, verified against Winetricks' checksums. The build intentionally fails
if an installer or an integrity check fails. Wine initialization and each
Winetricks component log their start and completion and have individual
timeouts. Initial prefix creation suppresses Wine's interactive Mono and Gecko
setup dialogs; the override applies only to initialization, not the running
client. Winetricks downloads are removed after installation in the same image
layer.

## CI and releases

The image build and publish jobs have a 30-minute timeout and use the
community BYOND mirror.
CI also checks Python, shell, YAML and Markdown formatting. To format the same
tracked files locally, install Python, Node.js and Git, then run:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install pre-commit==4.3.0
.venv/bin/pre-commit run --all-files
```

The formatters update files when needed; run the command again to confirm they
pass.

Pull requests and pushes to `main` build the image and smoke-test the Selkies
endpoint, Openbox, pager tray and BYOND pager, without logging in to a game
server. CI caches the initialized Wine prefix without BYOND in GitHub Actions;
the first successful build populates the cache, and branch access and cache
eviction affect reuse. The prefix cache key includes the Dockerfile and all
three installer scripts, so this runtime-library change invalidates old prefixes.
To test a fresh prefix locally, use the normal build command without a
`wine-prefix-cache` build context; the scratch stage provides an empty cache.
After formatting and image checks pass, CI publishes the tested image to
`ghcr.io/flashdim/tgstation-gateway:dev` for pushes or manual runs on `main`
and pull requests from this repository. Fork pull requests do not publish.
The mutable `dev` tag can contain unmerged pull-request code and points to the
most recently published image, not necessarily the latest commit on `main`.
Overlapping runs may finish out of order. Pull it again to get updates; it is
not a release or a Git tag.
To refresh unpinned components such as WebView2, delete the `wine-prefix-v2-`
cache in GitHub Actions and run CI on `main` again. Publishing a GitHub release
can reuse the default-branch cache, builds and tests the image again, then pushes it to
`ghcr.io/flashdim/tgstation-gateway` with the release tag. Non-prereleases also
update `latest`. Publishing requires Actions permission to write packages;
check third-party redistribution terms before creating a release.

## Private single-player experiment

The Compose example, direct Docker command and smoke tests use a custom profile
based on Docker's default seccomp profile. It adds one exception for the
32-bit `socket` syscall used by Wine; seccomp remains enabled for all other
syscalls. The base profile is copied from
[Moby's seccomp profile](https://github.com/moby/moby/blob/06db1734267bf7770914b417bff6556d835bf8cc/vendor/github.com/moby/profiles/seccomp/default.json).

The Compose example pulls the published image and runs one player container
bound to localhost:

```sh
docker compose -f examples/compose.yaml pull
docker compose -f examples/compose.yaml up
```

The `latest` tag is updated only by non-prerelease releases and will not be
available until the first such image is published. Prerelease images use their
release tag instead; change the image in the example to use one. GHCR may
require authentication depending on package visibility. The `pull` command
refreshes the mutable `latest` tag before starting the container.

Set `GATEWAY_IMAGE=ghcr.io/flashdim/tgstation-gateway:dev` to use the
experimental development image instead.

Set `GATEWAY_PORT` to change the localhost port. Run
`docker compose -f examples/compose.yaml down` to remove the container and its
player data. The published image uses its build-time BYOND version; to select
another version, build and run a local image as described above and below.

To connect directly instead of starting the pager, set
`BYOND_SERVER` to a hostname or IP address and port, optionally prefixed with
`byond://`:

```sh
BYOND_SERVER=ss13.lazorgator.party:1337 docker compose -f examples/compose.yaml up
```

Recreate the container to change the server. With `docker run`, pass the same
setting using `-e BYOND_SERVER=ss13.lazorgator.party:1337`. Leave it unset or
empty to start the pager as before. This requires an image built with this
change; an existing published `latest` image will not change until a new
release is published.

Alternatively, run the image built above directly:

```sh
docker run --rm --init --security-opt seccomp=examples/seccomp.json --shm-size=2g \
  -p 127.0.0.1:8080:8080 \
  tgstation-gateway-player
```

Open `http://localhost:8080`. Without `BYOND_SERVER`, the container starts the
BYOND pager; sign in there and connect to your server. With `BYOND_SERVER`, it
launches Dream Seeker directly; a BYOND account or server-side authentication
may still be required. A direct launch to the configured host has been observed,
but a complete authenticated gameplay session has not been documented.
The container health check requires the selected BYOND process and the Selkies
health endpoint; it does not verify a server connection or interactive gameplay.
Closing the browser does not automatically remove the container. Stop it with
Ctrl+C. No player data or BYOND login is intended to persist between containers.

The display defaults to a fixed **1920x1080** using Selkies'
`SELKIES_MANUAL_WIDTH=1920` and `SELKIES_MANUAL_HEIGHT=1080`. The pinned base
already starts X11 at 1920x1080, but normally resizes it to the browser on
connection; manual sizing keeps a consistent desktop instead. This does not
maximize Dream Seeker or guarantee that browser scaling distortion is resolved.
Override both variables to select a different fixed size. To restore automatic
browser-sized resolution, set both to `0` (in the environment when using Compose,
or with `-e SELKIES_MANUAL_WIDTH=0 -e SELKIES_MANUAL_HEIGHT=0` for `docker run`)
and recreate the container. Check the browser's scaling settings as well;
previously saved browser preferences may affect presentation.

There is no full desktop in this image. Openbox manages BYOND windows and
dialogs on the X11 display, which Selkies streams as a whole; this is not
per-window isolation. When starting the pager rather than a direct server
connection, a small system tray is provided for its icon. The launcher assumes
X11, not Selkies' Wayland backend. Earlier testing restored game and stat-panel
rendering by removing `LD_PRELOAD`, and confirmed audio with the LXQt-based
image. A later user-reported session rendered the menu, dialogs and audio, but
showed a black game scene with a few solid-color tiles after joining. The user
now reports that the extra startup dialogs disappear after connecting and that
there are no major rendering issues after restoring Ubuntu Wine packages as
runtime dependencies. These reports do not establish the root cause or complete
gameplay compatibility. CI smoke tests verify startup only. The desktop-free
image's pager/tray behavior also needs explicit verification.
The experimental Openbox maximization rule was removed after it made no
reported difference to startup window size.
No Dream Seeker startup maximize/fullscreen flag or persistent local sizing
configuration was verified in the client documentation search, so the launcher
does not pass speculative flags. BYOND documents
[`is-maximized` as a main-window skin parameter](https://github.com/byond-open-reference/byondref.com/blob/master/skinparams.html),
set by the game's interface or `winset()`, and the
[`.winset` client command](https://ref.dm-lang.org/skin/commands/dotwinset)
can change skin parameters after connecting. These are not executable startup
flags; applying them requires the game's actual main-window control ID.
Automatic game-window maximization remains unresolved. Do not maximize or hide
all `steam_proton` windows: the class alone does not distinguish game windows
from legitimate dialogs or WebView panels.

### AMD or Intel GPU experiment

The default Compose configuration uses software rendering. To try GPU
acceleration on a Linux Docker host with an AMD or Intel GPU, identify its DRM
render node under `/dev/dri`, then set its numeric group ID and add the GPU
override. For example, if the node is `/dev/dri/renderD128`:

```sh
export DRI_RENDER_GID="$(stat -c '%g' /dev/dri/renderD128)"
export GATEWAY_IMAGE=ghcr.io/flashdim/tgstation-gateway:dev
export BYOND_SERVER=ss13.lazorgator.party:1337
docker compose -f examples/compose.yaml -f examples/compose.gpu.yaml pull
docker compose -f examples/compose.yaml -f examples/compose.gpu.yaml up -d --force-recreate
```

Inspect the available nodes first if the host has multiple GPUs; use the group
ID of the intended render node. The group ID grants access but does not select
the GPU. To check whether the container can access that node and which OpenGL
renderer the X11 session uses:

```sh
docker compose -f examples/compose.yaml -f examples/compose.gpu.yaml exec player \
  sh -c 'test -r /dev/dri/renderD128 && test -w /dev/dri/renderD128 && echo "Render node accessible"'
docker compose -f examples/compose.yaml -f examples/compose.gpu.yaml exec player \
  sh -c '. "${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/container-env"; glxinfo -B'
```

Substitute the selected node for `renderD128`. An AMD or Intel renderer rather
than llvmpipe indicates hardware OpenGL; node access alone does not. This
override exposes the host's DRM devices to the container and requires compatible
host drivers. A user reported improved performance with the GPU override, but
the renderer was not independently confirmed. The health check cannot establish
GPU access or rendering. To return to software rendering, recreate the container
using only `examples/compose.yaml`.

To also try the experimental WebView2 GPU flags from
[Wine-Byond-help](https://github.com/kinggoldcatter/Wine-Byond-help/blob/main/issues.md),
set `BYOND_WEBVIEW2_GPU=1` before recreating the GPU-enabled container:

```sh
export BYOND_WEBVIEW2_GPU=1
docker compose -f examples/compose.yaml -f examples/compose.gpu.yaml up -d --force-recreate
```

This sets a Wine-prefix WebView2 policy for all WebView2 applications in the
container, bypassing the GPU blocklist and disabling DirectComposition. It may
increase memory use; a user reported no visible rendering improvement. It does
not disable Chromium site isolation. To disable the experiment, unset
`BYOND_WEBVIEW2_GPU` and recreate the container; restarting alone retains its
modified Wine prefix. This does not resolve server authentication failures.

Selkies uses WebSockets by default. Software rendering may be slow.
The image exposes a graphical session, not a hardened application sandbox.
The stream is unprotected by default. Operators are responsible for restricting
access and securing connections outside this project. Do not expose it directly
to the internet or share a container between players.
