# GitHub Actions workflows

`ci.yml` runs formatting, unit tests, Compose validation, image builds, smoke
tests for both display modes, and Wine runtime checks. It publishes the tested
development image for trusted branches and pull requests from this repository.
`publish.yml` tests and smoke-tests a release image before publishing it.

## Build caches

CI separately caches the checksum-pinned Proton Wine archive and clean
build-time Wine prefix. The archive cache key uses
`container/wine-proton.env`; the runner and image build verify the SHA-256.
Delete the corresponding `wine-download-v1-...` cache to refresh it. The
versioned prefix key includes the Dockerfile, Proton pin and installer inputs;
prefixes carry a Proton-version marker so runtimes cannot be mixed. Delete the
matching `wine-prefix-v4-proton-...` cache to force a fresh prefix. No cache
contains player session data.

The Ubuntu Wine 10 packages are installed as version-pinned runtime
dependencies, while Proton's standalone runtime is selected first in PATH.
The BYOND download remains versioned but has an optional checksum. Winetricks
downloads are avoided when the separate prefix cache hits. Formatting remains
a publication gate; unit tests, Compose validation, both CI display-mode smoke
tests, and runtime checks are retained rather than duplicating an image build.

## Issue 7 repaint UAT

`uat.yml` is a separate **workflow_dispatch-only** verification. Once the workflow
is present on the default branch, select **Issue 7 repaint UAT images → Run
workflow**, selecting the source branch to test. All jobs use that run's
full `github.sha`. It does not publish `dev`, `latest` or release tags and does
not change the release workflow.

The workflow builds one Wayland/XWayland test image with checksum-pinned
**Proton Wine 10.0-4** as the active runtime and Ubuntu Wine 10 packages as
runtime dependencies. Proton's archive version and checksum are maintained in
`container/wine-proton.env`; Ubuntu's Wine package version is pinned in the
Dockerfile. The image defaults to `SELKIES_WAYLAND=true`. Runtime checks verify
the selected executable, prefix marker, both architecture module sets,
linked-library dependencies and required Ubuntu packages.

The image retains the Dockerfile's digest-pinned Selkies
2.2.1/Ubuntu 26.04 base, BYOND 516.1689, WebView2 installation and fixed
1920×1080 display. DirectX setup runs BYOND's bundled DXSETUP and verifies the
installed `d3dx9_43` against its CAB before applying the native DLL override.
Winetricks installs DXVK; its pinned script resolves the latest DXVK GitHub
release when creating a fresh prefix, so that release is not version-pinned.
The Proton archive is cached separately from the Wine prefix and verified on
cache hits and downloads. `/opt/wine-proton/bin` stays first in PATH for
installation and player sessions, with Wine's loader and server selected from
that same runtime.
X11 uses Openbox;
Wayland uses Selkies' labwc with Wine on XWayland (not native Wine Wayland).
No compositor, window rule or resource tuning is introduced as a supposed fix.

The image must pass formatting, unit tests, runtime-library checks,
runtime/default-mode identity checks and its explicit display-mode smoke test
before publication. The **loaded, tested image is pushed**, not rebuilt.
The runner pulls the resulting digest as a publication check; that is an
authenticated runner pull, not proof that external testers have package access.
Check GHCR package visibility/access separately before inviting testers.
Existing commit-specific tags are refused, including on reruns, and uncertain
registry errors stop publication. Runtime-specific concurrency serializes same-SHA
runs. To change contents, use a new source commit; do not delete/reuse UAT tags.

UAT prefix keys use a separate `uat-wine-prefix-v3-proton-...` namespace
incorporating the Proton version, display mode and installer/Dockerfile hash.
There are no fallback restore keys. Prefixes carry a Proton-version marker,
checked before reuse, and
are archived from the clean image, never from a running player container.
Delete the matching UAT cache in Actions to refresh it; normal CI/release
caches remain separate.

The UAT job uploads a 30-day evidence artifact containing source/tag
identity, image metadata, installed package versions (including Openbox,
labwc and X servers), runner Docker resources, smoke output and, after
publication, the pullable digest reference. The job summary records the
published tag/digest and explicitly leaves interactive results pending.
Download these artifacts and copy the summary to issue #7 along
with the manual results below; preserve them beyond artifact expiry.

### Pull and run the Proton Wine image

Use the **full source SHA** from the workflow summary.
From a checkout of that source commit, using `examples/seccomp.json`, run:

```sh
SOURCE_SHA=<full-40-character-source-sha>
TAG_VARIANT=proton-10.0-4
IMAGE="ghcr.io/flashdim/tgstation-gateway:uat-issue-7-${SOURCE_SHA}-${TAG_VARIANT}-wayland"
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
Do not pass `SELKIES_WAYLAND`: the UAT tag must select its intended default.
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

Historical local validation of source `4b33669f6b7703588ac064042fc4aa6bb4366dfa`
downloaded and checksum-verified both actual Proton archives. The Proton
11.0-2/Wayland build passed the runtime dependency gate and Wine prefix
initialization, then stopped at Winetricks vcrun2022 because this sandbox
could not resolve `aka.ms` or its `web.archive.org` fallback. No integrity
checks or installer stages were bypassed. A complete local image, compositor
session, gameplay reproduction and image publication were therefore not
validated by that attempt; use the workflow on a runner with download access.
Those historical Proton results do not guarantee that the current image has
the same interactive behavior.

For the Proton Wine image, repeat this sequence at least five times:

1. Join the same game and wait for the same scene and UI to finish loading.
   Record game revision, BYOND version, browser/host/GPU/driver and image
   digest. Save `docker logs gateway-uat` locally and note trial start times.
2. Open and close the same named game dialog, then a WebView/TGUI dialog.
   Record their names and actions; do not substitute a different interface
   across trials.
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

| Runtime            | Display | Source SHA / tag / published digest | Tester pull | Dialog results | Resize results | Fullscreen results |
| ------------------ | ------- | ----------------------------------- | ----------- | -------------- | -------------- | ------------------ |
| Proton Wine 10.0-4 | Wayland | Pending publication                 | Pending     | Not tested     | Not tested     | Not tested         |

Include occurrence counts, measured delay, recovery behavior and evidence
links per cell, plus runtime/compositor versions and any configuration changes.
Do not close issue #7 until publication, tester pulls and interactive repaint
acceptance on Proton Wine are demonstrated. Previously published Proton tags
are historical images from older source commits, not this source commit.

## Historical Proton measurements

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
