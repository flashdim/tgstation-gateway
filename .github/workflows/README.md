# GitHub Actions workflows

`ci.yml` runs formatting, unit tests, Compose validation, image builds, smoke
tests for both display modes, and Wine runtime checks. It publishes the tested
development image for trusted branches and pull requests from this repository.
`publish.yml` tests and smoke-tests a release image before publishing it.

## Build caches

CI caches the checksum-pinned Proton Wine archive separately from the Wine
prefix. The archive cache key uses `container/wine-proton.env` (version and
SHA-256); both the runner and image build verify the checksum. An invalid cache
fails the build: delete the corresponding `wine-download-v1-...` GitHub Actions
cache to refresh it. The prefix cache key includes the Dockerfile and installer
inputs, including the Wine pin; delete the matching `wine-prefix-v2-...` cache
to force a fresh prefix. Neither cache contains player session data. Local
builds without the download cache fetch and verify the archive normally.

The BYOND download remains versioned but has an optional checksum, and the
DXVK archive is checksum-pinned but not cached. Winetricks downloads are
avoided when the separate prefix cache hits. Formatting remains a publication
gate; unit tests, Compose validation, both CI display-mode smoke tests, and
runtime checks are retained rather than duplicating an image build.

## Measurements

For comparison, [CI run 44012025718](https://github.com/flashdim/tgstation-gateway/actions/runs/44012025718)
restored the prefix in 4 seconds and built the image in 3m55s. APT fetched
380 MB in 3 seconds, and the Proton download and checksum finished within
0.59 seconds; extraction took the rest of that 5.8-second step. In a local
test the 70.4 MB archive took 1.26 seconds to download and verify, versus
0.05 seconds to verify an existing copy. In
[CI run 44013258570](https://github.com/flashdim/tgstation-gateway/actions/runs/44013258570)
the warm download cache restored in 2 seconds and runner verification took
less than a second. Its image build took 5m43s and passed both smoke tests
and runtime checks, but missed the newly keyed prefix cache, so it is not
directly comparable with the baseline prefix hit. Cache transfer and repeated
verification may outweigh the saved download time.
