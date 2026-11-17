# GitHub Actions workflows

`ci.yml` runs formatting, unit tests, Compose validation, image builds, smoke
tests for both display modes, and Wine runtime checks. It publishes the tested
development image for trusted branches and pull requests from this repository.
`publish.yml` tests and smoke-tests a release image before publishing it.

## Build caches

CI and release workflows separately cache the checksum-pinned GE-Proton
archive and clean build-time Proton prefix. The archive cache key uses
`container/ge-proton.env`; the runner and image build verify the published
SHA-512 checksum. Delete the corresponding `ge-proton-download-v1-...` cache to
refresh it. The versioned prefix key includes the Dockerfile, GE-Proton pin and
installer inputs; prefixes carry a GE-Proton version marker so runtimes cannot
be mixed. Delete the matching `wine-prefix-v5-ge-proton-...` cache to force a
fresh prefix. No cache contains player session data.

Ubuntu Wine 10 packages are installed as version-pinned runtime dependencies,
while GE-Proton is the active runtime and its launcher starts BYOND. The BYOND
download remains versioned but has an optional checksum. Winetricks downloads
are avoided when the separate prefix cache hits. Successful startup smoke tests
do not demonstrate interactive gameplay or rendering compatibility.
