# GitHub Actions workflows

`ci.yml` runs formatting, image builds, unit tests, Compose validation, smoke
tests for both display modes, and Wine runtime checks. After formatting passes,
unit tests run in a separate job in parallel with the image build and development
image push. Unit-test failures fail the workflow but do not block that push.
CI publishes the development image immediately after the build for trusted
branches and pull requests from this repository, before Compose validation,
smoke tests, and runtime checks. The `dev` tag may therefore point to an image
that fails validation.
`publish.yml` tests and smoke-tests a release image before publishing it.

## Build caches

CI and release workflows separately cache the checksum-pinned Proton Wine
archive and clean build-time Wine prefix. The archive cache key uses
`container/wine-proton.env`; the runner and image build verify its SHA-256.
Delete the corresponding `wine-download-v1-...` cache to refresh it. The
versioned prefix key includes the Dockerfile, Proton pin and installer inputs.
Prefixes carry a Proton-version marker so runtimes cannot be mixed. Delete the
matching `wine-prefix-v4-proton-...` cache to force a fresh prefix. No cache
contains player session data.

Ubuntu Wine 10 packages are installed as version-pinned runtime dependencies,
while Proton's standalone runtime is selected first in PATH. Graphics setup
runs BYOND's bundled DirectX installer, verifies the installed `d3dx9_43.dll`
against BYOND's CAB and configures the native DLL override. It also installs
checksum-verified DXVK 3.1.1. The BYOND download remains versioned but has an
optional checksum. Successful
startup smoke tests do not demonstrate interactive gameplay or rendering
compatibility.
