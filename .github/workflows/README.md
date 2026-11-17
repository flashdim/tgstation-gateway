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

## Issue 7 repaint UAT

`uat.yml` is a separate **workflow_dispatch-only** comparison. Once the workflow
is present on the default branch, select **Issue 7 repaint UAT images → Run
workflow**, selecting the source branch to compare. All jobs use that run's
full `github.sha`. It does not publish `dev`, `latest` or release tags and does
not change the release workflow.

The fail-fast-disabled matrix builds actual checksum-pinned standalone
Kron4ek Proton Wine **10.0-4** and **11.0-2**, each with **X11** and
**Wayland/XWayland** defaults. Build arguments `WINE_PROTON_VERSION` and
`SELKIES_WAYLAND` select the runtime and default mode. Unknown runtimes fail
closed. Proton 11.0-2's amd64 SHA-256 is taken from its
[upstream release](https://github.com/Kron4ek/Wine-Builds/releases/tag/proton-11.0-2);
this is not the amd64-wow64 artifact.
The Proton 10 archive has `bin/wine-preloader`; Proton 11 relocates its
preloaders and architecture-specific loaders under `lib/wine/*-unix/`.
Build and runtime checks require the version-appropriate paths rather than
adding compatibility symlinks or skipping loader checks.
The Proton 11 i386 GStreamer module also requires `libgstgl-1.0.so.0`;
`libgstreamer-gl1.0-0:i386` is installed in all variants to keep their
dependencies comparable. Supplemental APT libraries remain repository-selected
(not version-pinned); the per-image package inventory records their versions.

All variants retain the Dockerfile's identical digest-pinned Selkies
2.2.1/Ubuntu 26.04 base, BYOND 516.1689, DXVK 2.7.1, WebView2 installation,
fixed 1920×1080 display and Ubuntu Wine runtime dependencies. X11 uses Openbox;
Wayland uses Selkies' labwc with Wine on XWayland (not native Wine Wayland).
No compositor, window rule or resource tuning is introduced as a supposed fix.

Each variant must pass formatting, unit tests, runtime-library checks,
runtime/default-mode identity checks and its explicit display-mode smoke test
before publication. The **loaded, tested image is pushed**, not rebuilt.
The runner pulls the resulting digest as a publication check; that is an
authenticated runner pull, not proof that external testers have package access.
Check GHCR package visibility/access separately before inviting testers.
Existing commit-specific tags are refused, including on reruns, and uncertain
registry errors stop publication. Per-variant concurrency serializes same-SHA
runs. To change contents, use a new source commit; do not delete/reuse UAT tags.

Download keys use `uat-wine-download-v1-<proton>-<pin/script hash>`.
Prefix keys use `uat-wine-prefix-v1-<proton>-<display>-<installer/Dockerfile hash>`.
There are no fallback restore keys. Cached archives are verified again in
the image build. Prefixes carry a runtime marker, checked before reuse, and
are archived from the clean image, never from a running player container.
Delete the matching UAT cache in Actions to refresh it; normal CI/release
caches remain separate.

Each matrix job uploads a 30-day evidence artifact containing source/tag
identity, image metadata, installed package versions (including Openbox,
labwc and X servers), runner Docker resources, smoke output and, after
publication, the pullable digest reference. The job summary records the
published tag/digest and explicitly leaves interactive results pending.
Download these artifacts and copy the four summaries to issue #7 along
with the manual results below; preserve them beyond artifact expiry.
Failures in one matrix entry do not cancel the other entries.

### Pull and run the comparison

Use the **same full source SHA** from the workflow summary for all four tags.
From a checkout of that source commit, using `examples/seccomp.json`, run:

```sh
SOURCE_SHA=<full-40-character-source-sha>
PROTON=10.0-4 # repeat with 11.0-2
DISPLAY_MODE=x11 # repeat with wayland
IMAGE="ghcr.io/flashdim/tgstation-gateway:uat-issue-7-${SOURCE_SHA}-proton-${PROTON}-${DISPLAY_MODE}"
docker pull "$IMAGE"
docker image inspect --format '{{json .RepoDigests}}' "$IMAGE"
docker run --rm --name gateway-uat --init \
  --security-opt seccomp=examples/seccomp.json \
  --cpus=4 --memory=8g --shm-size=2g \
  -p 127.0.0.1:8080:8080 \
  -e SELKIES_MANUAL_WIDTH=1920 -e SELKIES_MANUAL_HEIGHT=1080 \
  -e BYOND_WEBVIEW2_GPU=0 \
  -e BYOND_SERVER=server.example.org:1337 \
  "$IMAGE"
```

Replace the server with the same operator-authorized test server for every run.
Open <http://localhost:8080>. Only local TCP port 8080 is published; no Docker
API, game-server port or unprotected remote desktop port is exposed.
Authentication and TLS remain external operator responsibilities. The resource
limits are a controlled comparison budget, **not validated capacity guidance**.
Do not pass `SELKIES_WAYLAND`: each tag must select its own intended default.
Do not mount an existing Wine prefix or player data. Use a fresh container
for every trial, the same browser/zoom/viewport, host, GPU exposure (none in
this baseline), client/server version, network and interaction sequence.
Record any deviation, including an inability to meet this resource budget.
For digest-locked repeats, replace `"$IMAGE"` with the summary's
`ghcr.io/flashdim/tgstation-gateway@sha256:...` reference.

### Repaint investigation and results

**Status:** the report describes incorrect redraw after dialogs, resizing and
fullscreen, but does not establish whether pixels are delayed, stale, blank or
permanently lost. No measured reproduction or causal correction is available
yet. The repository's earlier Wine/DXVK/LD_PRELOAD experiments in `ROADMAP.md`
are not evidence for the cause of this particular failure. No window hiding,
Openbox replacement or compositor workaround has been applied.

For **each** matrix entry, repeat this sequence at least five times:

1. Join the same game and wait for the same scene and UI to finish loading.
   Record game revision, BYOND version, browser/host/GPU/driver and image
   digest. Save `docker logs gateway-uat` locally and note trial start times.
2. Open and close the same named game dialog, then a WebView/TGUI dialog.
   Record their names and actions; do not substitute a different interface
   across variants.
3. Resize the game window from maximized to approximately 1280×720 and back.
   Toggle the **game window's** fullscreen on/off separately from browser
   fullscreen; record exact controls and geometry used.
4. Record event-to-correct-frame delay in milliseconds from a timestamped
   screen recording, occurrence count/trials and maximum delay. Distinguish
   delayed repaint, stale regions, blank regions and persistent failure
   (still incorrect after 10 seconds). Note whether input and sound continue.
5. If broken, test recovery actions one at a time: move/occlude/uncover the
   window, minimize/restore, resize again, reconnect the browser, restart the
   client. Record the first recovery, or that none worked. Check a second
   desktop window too. If available, compare a local X display capture with
   the browser recording: correct local pixels but stale browser pixels
   points toward capture/encoding rather than BYOND painting.

Capture read-only session identity while the trial is running:

```sh
docker exec gateway-uat sh -c '
  . "${XDG_RUNTIME_DIR:-/tmp/runtime-ubuntu}/container-env"
  printf "wayland=%s display=%s\n" "$SELKIES_WAYLAND" "$DISPLAY"
  ps -eo pid,comm,args | grep -E "openbox|labwc|Xwayland|Xvfb|Xorg"
  xdpyinfo -display "$DISPLAY" | head -25
  dpkg-query -W | grep -Ei "openbox|labwc|xwayland|xserver|selkies"
'
docker stats --no-stream gateway-uat
```

Keep logs/recordings local until reviewed and redacted: they can contain
account names, chat, server addresses or authentication material. Do not upload
player data as CI artifacts. Record exact compositor package versions from
the evidence artifact and actual running processes/settings above, not just
the Selkies tag. If an alternate desktop/compositor is needed, pin it, give it
a separate configuration-identifying UAT tag, and change only that variable.

Publication and interactive acceptance are **pending**, not implied by this
workflow or by startup smoke tests. Fill in and post this table to issue #7
after dispatch and user testing:

| Proton | Display | Source SHA / tag / published digest | Tester pull | Dialog results | Resize results | Fullscreen results |
| ------ | ------- | ----------------------------------- | ----------- | -------------- | -------------- | ------------------ |
| 10.0-4 | X11     | Pending publication                 | Pending     | Not tested     | Not tested     | Not tested         |
| 10.0-4 | Wayland | Pending publication                 | Pending     | Not tested     | Not tested     | Not tested         |
| 11.0-2 | X11     | Pending publication                 | Pending     | Not tested     | Not tested     | Not tested         |
| 11.0-2 | Wayland | Pending publication                 | Pending     | Not tested     | Not tested     | Not tested         |

Include occurrence counts, measured delay, recovery behavior and evidence
links per cell, plus runtime/compositor versions and any configuration changes.
Do not close issue #7 until publication, tester pulls and interactive repaint
acceptance (including both display modes) are demonstrated.

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
