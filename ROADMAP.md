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
- Use Selkies' Wayland session with labwc by default, with an X11/Xvfb
  comparison mode and a pager tray; support optional AMD/Intel GPU access.
- Keep seccomp enabled with a narrowly scoped exception for Wine's 32-bit
  `socket` syscall; use the same profile in examples and smoke tests.
- Build and publish the development image before CI validation; publish the
  release image only after it passes tests and smoke tests.

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
In disposable comparisons, Ubuntu Wine 10 rendered the scene but fancy chat and
the stat panel failed; standalone Proton Wine 11.0-2 rendered the scene and
panels, but initially showed two extra dialogs under Wayland/XWayland. The user
now reports those windows appear briefly and disappear after connecting, and
that there are no major rendering issues after restoring Ubuntu Wine packages
as runtime dependencies. The dialog cause was not isolated and no suppression
was added. The Openbox maximization rule made no reported size change and was
removed.

The previous image used checksum-pinned Proton Wine 10.0-4 as the active
runtime, Ubuntu's pinned Wine packages for runtime dependencies, and BYOND
516.1689. CI built and published that image after a retry; X11 and Wayland
startup smoke tests and Wine runtime checks passed. The first build attempt
failed during core-font registration after a Wine connection reset, but the
retry passed. These checks do not prove interactive gameplay, game-scene
rendering, WebView compatibility, or complete dialog behavior.

The active runtime is checksum-pinned standalone Proton Wine 10.0-4; Ubuntu
Wine 10 packages provide runtime dependencies. WineHQ staging and GE-Proton
experiments were reverted and are not part of the current image. Its graphics
setup runs BYOND's bundled DirectX installer for `d3dx9_43`, verifies the
installed DLL against BYOND's CAB, and configures the native DLL override.
Winetricks installs DXVK through its `dxvk` verb; the resolved DXVK release is
not separately version-pinned. An earlier attempt to install native
`d3dx9_43` did not improve the scene, but the user reports that restoring
BYOND's bundled DirectX installer fixed the lighting rendering issue in the
current setup. This points to the bundled installer being important for
lighting in that test; it does not establish the underlying mechanism or
guarantee compatibility across other hosts/configurations. Startup and runtime
checks still do not prove gameplay or rendering. A Mesa Vulkan experiment
added i386 and x86_64 drivers and lavapipe ICD manifests, but did not improve
rendering; those additions have been removed.
Build and interactive compatibility on other configurations remain to be
verified; prior results are not proof of universal gameplay compatibility.

The image defaults to fixed 1920x1080 Selkies resolution. This display-size
experiment was prompted by reported first-connection scaling distortion;
whether it improves browser scaling remains unverified. Automatic Dream Seeker
maximization also remains unresolved. No verified Dream Seeker startup flag or
local sizing setting was found; BYOND's documented maximization parameter is a
game-skin setting, not an executable command-line option.

Earlier testing found that removing Selkies' `LD_PRELOAD` restored game and
stat-panel rendering in its test environment; it did not establish the cause
of other rendering behavior. A direct launch to the configured host has been
observed. A complete authenticated gameplay session and release publication
remain unverified.

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
