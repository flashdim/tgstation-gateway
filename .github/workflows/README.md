# GitHub Actions workflows

For pull requests, `ci.yml` compares the checked-out merge result with the
current base commit. For pushes to main it compares the previous and new
commits, covering the whole push rather than just its final commit. Changes
under `container/`, `landing/`, `examples/` or `tests/`, the root Dockerfile
or `.dockerignore`, the pre-commit configuration, or either workflow run the
full CI pipeline. These conservative paths also cover validation and build
configuration changes. Update them when image inputs or validation move.
Other changes, such as documentation-only changes, leave the formatting job
successful and the remaining jobs skipped (which GitHub treats as successful
required checks). No development images or screenshots are produced in that
case. If the comparison base is unavailable, CI runs in full; manually
dispatching the workflow also runs it in full. Release publishing is unaffected.

`ci.yml` runs formatting, image builds, unit tests, Compose validation, smoke
tests for both display modes, and Wine runtime checks. The X11 player smoke test
also queries Wine's BYOND `userpath` registry value. After formatting passes,
unit tests run in a separate job in parallel with the image build and development
image push. Unit-test failures fail the workflow but do not block that push.
CI publishes `dev` for main and `dev-pr<number>` for pull requests from this
repository immediately after the build, before Compose validation, smoke tests,
and runtime checks. These tags may therefore point to images that fail
validation.
The player image (`image` job), landing image (`landing-image` job) and manager
image (`manager-image` job) are built, published and tested in separate jobs
that run in parallel after formatting; a failure in one does not cancel the
others. Compose validation runs in the player job. The same development tags
are published for `ghcr.io/<owner>/<repository>-landing` and
`ghcr.io/<owner>/<repository>-manager`. CI publishes the development manager
image before its integration test, so a development tag can point to an image
that fails validation.
`publish.yml` runs unit tests first, then builds, tests and publishes the
player, landing and manager images in parallel jobs. Each image is published
only after its own checks pass, but jobs do not wait for each other: if one
fails, other images may already be published for that release. Re-run the
failed job for transient failures; otherwise fix the cause in a new release.
After unit tests pass, `landing-screenshot` renders the landing page with five
slots in Chromium and uploads a desktop `landing-desktop.png` as an unzipped
artifact, downloadable from the run summary. It uses Ubuntu 24.04 because the
Ubuntu 26.04 runner's Microsoft package repository returned HTTP 403 during
Playwright's dependency installation. It is a visual aid, not a gameplay check.
The landing image is smoke-tested by generating slots from `GATEWAY_PLAY_HOST`
and related environment variables, checking the generated links, rejecting an
invalid host, and checking that it serves the page files and attribution.
Release tags match the GitHub release tag; stable releases also update `latest`,
while prereleases do not. For a local landing build, run
`docker build -f landing/Dockerfile -t tgstation-gateway-landing:local .` from
the repository root. Set `GATEWAY_LANDING_IMAGE` to select this local image or
the published `dev` image in the Compose example. See the main README for the
landing environment variables.

The landing page lists configured account links without monitoring the fixed
containers; the game-server status
panel is a separate read-only `?status` query and does not authenticate users,
create or isolate sessions, or enforce ownership. `#shared` is not an
authorization boundary. Operators must provide external access controls and
secure connections; trusted ownership and credential provisioning remain
future integration work.

Both workflows also exercise fixed-account isolation, restart, service recovery,
count and prefix changes, unrelated projects and volume retention/cleanup using
a pinned Alpine fixture. This does not test daemon or host restarts, the player
image, authenticated routing, Selkies disconnect behavior or gameplay.

Both workflows test the locally built manager image in the managed Traefik
Compose deployment with pinned Traefik and mock backends, including HTTPS
routes, WebSocket upgrades, slot-count reconciliation and retained volumes.
The mock player image is pushed to a temporary loopback-only registry so the
manager exercises its startup pull, including on restarts.
Restarting the manager must recreate both players and retain markers in their
Wine and data volumes; subsequent reconciliation must not recreate them again.
An unowned later-slot container must leave existing players untouched across
manager retries; unit fixtures also exercise interrupted startup recovery.
The test verifies the running manager uses the image built for that job. This
does not exercise Cloudflare or live gameplay.

The launcher unit test uses a mock Wine executable to verify pager startup and
configuration. Login and saving credentials are operator actions in the pager;
CI does not enter credentials or authenticate real accounts.

## Build caches

CI and release workflows separately cache the checksum-pinned Proton Wine
archive and clean build-time Wine prefix. The archive cache key uses
`container/wine-proton.env`; the runner and image build verify its SHA-256.
Delete the corresponding `wine-download-v1-...` cache to refresh it. The
versioned prefix key includes the Dockerfile, Proton pin and installer inputs.
Prefixes carry a Proton-version marker so runtimes cannot be mixed. Delete the
matching `wine-prefix-v4-proton-...` cache to force a fresh prefix. No cache
contains player session data.

On a cache miss, the prefix installer retries Winetricks `corefonts` up to
five times after Wine shuts down if registration exits with status 1. A sixth
failure still stops the build.

Ubuntu Wine 10 packages are installed as version-pinned runtime dependencies,
while Proton's standalone runtime is selected first in PATH. Graphics setup
runs BYOND's bundled DirectX installer, verifies the installed `d3dx9_43.dll`
against BYOND's CAB and configures the native DLL override. It also installs
checksum-verified DXVK 3.1.1. The BYOND download remains versioned but has an
optional checksum. Successful
startup smoke tests do not demonstrate interactive gameplay or rendering
compatibility.

The X11 smoke test checks the desktop defaults' ownership and permissions;
both desktop smoke tests query Plasma's panel properties. These checks do not
verify the supplied wallpaper visually, game-window geometry, or interactive
gameplay.
When changing the pinned Selkies base, rerun both smoke tests and manually
verify the first-run desktop layout in both display modes.
