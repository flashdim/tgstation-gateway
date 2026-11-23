# GitHub Actions workflows

`ci.yml` runs formatting, image builds, unit tests, Compose validation, smoke
tests for both display modes, and Wine runtime checks. After formatting passes,
unit tests run in a separate job in parallel with the image build and development
image push. Unit-test failures fail the workflow but do not block that push.
CI publishes `dev` for main and `dev-pr<number>` for pull requests from this
repository immediately after the build, before Compose validation, smoke tests,
and runtime checks. These tags may therefore point to images that fail
validation.
The same development tags are published for the separate
`ghcr.io/<owner>/<repository>-landing` image. `publish.yml` tests and
smoke-tests the player image and landing image before publishing either release.
The landing image is smoke-tested by replacing its default `slots.js` with a
read-only mount and checking that it serves the page files and attribution.
Release tags match the GitHub release tag; stable releases also update `latest`,
while prereleases do not. For a local landing build, run
`docker build -f landing/Dockerfile -t tgstation-gateway-landing:local .` from
the repository root. Set `GATEWAY_LANDING_IMAGE` to select this local image or
the published `dev` image in the Compose example. `GATEWAY_LANDING_SLOTS` can
point to an operator-provided host file, mounted read-only as `/srv/landing/slots.js`.

The landing page uses static test status only; it does not authenticate users,
create or isolate sessions, or enforce ownership. `#shared` is not an
authorization boundary. Operators must provide external access controls and
secure connections; live session status, trusted ownership and credential
provisioning remain future integration work.

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
