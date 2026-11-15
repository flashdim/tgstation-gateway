# tgstation-gateway

An experimental browser-accessible BYOND client for tgstation. The intended
design is a separate, disposable Wine/BYOND container for each player, with a
session manager. The game server and tgstation-server remain separate.

**Current scope:** a single-player Docker image framework. Session creation,
resource limits and cleanup are not implemented. This is intended for private
self-hosting and is not ready for multi-user deployment.

See [ROADMAP.md](ROADMAP.md) for milestones and acceptance criteria.

## Build the player image

The image uses the Selkies desktop image for a headless X11 display, audio and
browser streaming. It installs Wine Staging 11.14 and uses Winetricks to install
Visual C++ 2022, DirectX components and WebView2. It also installs BYOND. It targets
`linux/amd64` and an x64 Wine prefix; this combination has not yet been
validated end to end. DXVK is not installed for this rendering experiment;
Wine's built-in Direct3D implementation is used instead. See the community
[Wine-Byond-help guide](https://github.com/kinggoldcatter/Wine-Byond-help) for
BYOND-specific Wine troubleshooting.

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
client. Winetricks downloads are removed after installation in the same image
layer.

## CI and releases

The image build and publish jobs have a 15-minute timeout and use the
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
endpoint and BYOND pager, without logging in to a game server. CI caches the
initialized Wine prefix without BYOND in GitHub Actions; the first successful
build populates the cache, and branch access and cache eviction affect reuse.
After formatting and image checks pass, CI publishes the tested image to
`ghcr.io/flashdim/tgstation-gateway:dev` for pushes or manual runs on `main`
and pull requests from this repository. Fork pull requests do not publish.
The mutable `dev` tag can contain unmerged pull-request code and points to the
most recently published image, not necessarily the latest commit on `main`.
Overlapping runs may finish out of order. Pull it again to get updates; it is
not a release or a Git tag.
To refresh unpinned components such as WebView2, delete the `wine-prefix-v1-`
cache in GitHub Actions and run CI on `main` again. Publishing a GitHub release
can reuse the default-branch cache, builds and tests the image again, then pushes it to
`ghcr.io/flashdim/tgstation-gateway` with the release tag. Non-prereleases also
update `latest`. Publishing requires Actions permission to write packages;
check third-party redistribution terms before creating a release.

## Private single-player experiment

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

Set `GATEWAY_PORT` to change the localhost port. Run
`docker compose -f examples/compose.yaml down` to remove the container and its
player data. The published image uses its build-time BYOND version; to select
another version, build and run a local image as described above and below.

To attempt a direct connection instead of starting the pager, set
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
docker run --rm --init --shm-size=2g \
  -p 127.0.0.1:8080:8080 \
  tgstation-gateway-player
```

Open `http://localhost:8080`. Without `BYOND_SERVER`, the container starts the
BYOND pager; sign in there and connect to your server. With `BYOND_SERVER`, it
launches Dream Seeker directly; a BYOND account or server-side authentication
may still be required. Direct connection and interactive gameplay have not
been validated end to end.
The container health check requires the selected BYOND process and the Selkies
health endpoint; it does not verify a server connection or interactive gameplay.
Closing the browser does not automatically remove the container. Stop it with
Ctrl+C. No player data or BYOND login is intended to persist between containers.

Selkies uses WebSockets by default. Software rendering may be slow; GPU access
and hardware-specific configuration require separate testing. Whether Wine
Staging improves rendering has not yet been verified.
The image exposes a desktop environment, not a hardened application sandbox.
The stream is unprotected by default. Operators are responsible for restricting
access and securing connections outside this project. Do not expose it directly
to the internet or share a container between players.
