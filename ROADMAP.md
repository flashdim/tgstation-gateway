# Roadmap

## Goal and boundaries

Enable players to use the standard Windows BYOND client in a browser to play
one operator-configured tgstation server. The first multi-player deployment
targets one Docker host: a session manager creates a disposable player
container on demand for each player. Keep the game server and
tgstation-server separate; neither is managed by this project.

This is a private, self-hosted solution. Access control and connection security
are the operator's responsibility outside the project. The gateway must still
isolate sessions and provide a clear, enforceable boundary for those external
controls. Do not assume a particular proxy or identity provider.

Milestones are ordered by dependency, not dates. An item is complete only when
its acceptance criteria are demonstrated and documented. Exact implementation
choices and performance targets remain open until supported by measurements.

## 1. Player image foundation — in progress

Provide an independently usable, single-player Wine/BYOND image.

- Build a version-selectable BYOND client from the community mirror with Wine,
  Winetricks dependencies and browser streaming; support an optional checksum.
- Start the BYOND pager or connect directly to an operator-configured server;
  expose the streaming endpoint and provide local Compose examples.
- Use a desktop-free X11 session with Openbox and a pager tray; support optional
  AMD/Intel GPU access.
- Keep seccomp enabled with a narrowly scoped exception for Wine's 32-bit
  `socket` syscall; use the same profile in examples and smoke tests.
- Build and smoke-test the image in CI, publish a tested development image and
  publish the tested image on release.

**Progress:** CI has built, smoke-tested and published the desktop-free `dev`
image. A user report confirms that the menu, dialogs and audio work, but the
game scene becomes black with a few solid-color tiles after joining, with and
without GPU access. Installing native `d3dx9_43` did not improve the scene.
With DXVK 2.7.1, the map stayed black; Dream Seeker loaded DXVK's D3D9 library
and logged device resets, but its viewport did not show a DXVK HUD. The map
also remained black with Wine 11.15, Ubuntu's stock Xvfb and Selkies'
Wayland/XWayland session. The same BYOND version was reported working on the
same GPU with Proton 11.0-2. Using Proton's D3D9 DXVK library with Wine did
not fix the map, although Dream Seeker loaded it. The image now installs
32-bit FreeType and Fontconfig, which removed FreeType errors in a separate
Proton Wine initialization test, but did not resolve the black map.
In a disposable container a fresh Ubuntu Wine 10 prefix with BYOND's bundled
DirectX setup, native `d3dx9_43` and DXVK 2.7.1 rendered the scene, but fancy
chat and the stat panel failed. A fresh standalone Proton-based Wine 11.0-2
prefix rendered the scene and loaded both panels, but showed two extra blank
dialogs under Wayland/XWayland; [issue #4](https://github.com/flashdim/tgstation-gateway/issues/4)
tracks them. The previously tested image used that runtime; the individual
cause is unconfirmed. The user reports that standalone Wine 11.22 removed the
extra windows but restored the rendering issue. The Dockerfile now pins
checksum-verified standalone Wine 11.19 for an intermediate-release comparison.
Wine 11.20's release notes warn of a startup segmentation fault on some systems,
so 11.19 is the nearest earlier release without that warning. Its official
archive checksum and required Wine binaries were verified, and an image build
completed Wine prefix initialization and startup. The build then failed to
download Winetricks' `vcrun2022` dependency because DNS resolution for Microsoft
and Archive.org hosts was unavailable. Dream Seeker rendering and dialog
behavior remain unverified with Wine 11.19; no fix is presumed.
A built-image comparison did not reproduce the persistent dialog pair with
Dream Seeker alone or a minimal diagnostic world. An untitled browser dialog
had the same broad X11 properties, so no window-suppression rule is applied.
Openbox now stays idle under Wayland, where labwc manages XWayland windows,
instead of repeatedly failing to start. Both backend startup smoke tests
passed with that script overlaid on the published image; this does not resolve
issue #4 or verify tgstation gameplay. See the README's dialog investigation
for results and the remaining manual checks.
Earlier testing found that removing Selkies' `LD_PRELOAD` restored game and
stat-panel rendering in that test environment; it does not resolve or rule out
the current failure. A direct launch to the configured host has been observed.
The release publication path and a complete playable gameplay session remain
unverified.

**Exit:** a clean build starts the streaming service and BYOND process, with
build, configuration and limitations documented. The smoke test does not
demonstrate interactive play or the release publish.

## 2. Verify real gameplay

Prove that the image is usable against an actual tgstation server before
building session orchestration around it.

- Manually verify browser connection, BYOND login and joining a test server.
- Reproduce and diagnose the reported black game scene with solid-color tiles;
  record the client, Wine and rendering configuration for each test.
- Verify map rendering, TGUI/WebView2, keyboard and mouse input, sound,
  dialogs, pager/tray behavior, disconnect and reconnect; record supported
  versions and limitations.
- Measure startup time, responsiveness and per-player CPU, memory, GPU and
  bandwidth requirements. Compare software and available GPU rendering rather
  than assuming either is sufficient.
- Test two independent clients for shared source IP and BYOND computer-ID
  behavior; document implications for bans and operator policy.

**Exit:** record a reproducible test environment and results for a playable
session, including any unresolved compatibility, performance or identity
limitations. Define deployment budgets from those measurements.

## 3. Single-host session lifecycle

Introduce a lightweight manager that runs on one Docker host and keeps the
player image independently usable. A request starts a separate container for
one player and targets the operator-configured server; it must not allow
arbitrary player-selected server destinations.

- Define the session API and configuration, including startup, readiness,
  failure, explicit termination, idle expiration and reconnect behavior.
- Route browser traffic, including streaming connections, to the correct
  session. Define how the external access-control boundary supplies or
  verifies session ownership before routing; untrusted client headers or
  guessed session identifiers must not grant access.
- Enforce session capacity and per-container resource limits. Handle concurrent
  requests, startup failures and timeouts with explicit errors.
- Reconcile managed containers after manager restart and clean up expired,
  failed and orphaned sessions without affecting unrelated containers.
- Keep the Docker API private to the manager, never exposed to players. Treat
  access to the Docker daemon as privileged and document that trust boundary.

**Exit:** integration tests demonstrate two isolated sessions, correct
routing and ownership enforcement, capacity handling, cleanup and recovery;
an operator can configure and run the manager on one host. External access
controls remain required.

## 4. Private deployment readiness

Make the single-host system practical to operate without presenting it as
public or multi-host infrastructure.

- Validate multiple real clients, including simultaneous logins and gameplay,
  against the configured server. Resolve or clearly document shared-IP and
  computer-ID limitations without bypassing server bans.
- Test resource exhaustion, disconnects, container crashes, host/manager
  restarts and cleanup of session data. Verify credentials and player data do
  not leak between sessions or into logs, images or caches.
- Document installation, upgrades, capacity planning, troubleshooting,
  backup/recovery expectations and the external access-control contract.
- Review isolation, dependency updates and redistribution/hosted-use terms for
  BYOND and other third-party components before publishing or deploying.

**Exit:** demonstrate the documented private deployment with multiple
players, measured limits and recovery procedures; disclose remaining risks and
unsupported configurations.

## Later considerations

Multi-host scheduling, high availability, multiple server destinations and
other scaling features are outside the first deployment target. Revisit them
only after the single-host milestones establish actual requirements.
