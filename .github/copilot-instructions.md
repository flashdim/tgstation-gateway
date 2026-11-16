# Project guidance

Read `ROADMAP.md` for the goal, milestone order and acceptance criteria.
The current image is an experimental single-player foundation; do not describe
planned features or smoke tests as proof of interactive gameplay.

## Architecture

- Use Wine and the real Windows BYOND client; do not reimplement the BYOND
  protocol. Keep the game server and tgstation-server separate from sessions.
- Target a single Docker host and one operator-configured BYOND server first.
  Keep the player image usable without a manager. Do not introduce multi-host
  orchestration or player-selected destinations without an explicit decision.
- Future session management must create, route, limit and clean up a separate
  container per player, and recover safely after failures or restarts. Manage
  only containers belonging to this project.
- Access control and connection security are external operator responsibilities;
  do not couple the project to a particular proxy, identity provider or TLS
  setup. Define and enforce the session ownership boundary before routing:
  never trust client-supplied identity headers or session IDs by themselves.
- Never expose the Docker API to players. Treat daemon access as privileged and
  isolate each desktop, Wine prefix, credentials and session data from other
  players. Do not log secrets or include player data in images or caches.
- BYOND may see shared IP addresses or computer IDs. Investigate and document
  collisions and preserve server ban enforcement; never silently bypass it.
- The player image uses checksum-pinned standalone Wine 11.22; Ubuntu Wine
  packages supply its runtime libraries. Keep the 32-bit runtime dependencies,
  BYOND's bundled DirectX setup, native `d3dx9_43` and pinned DXVK version
  consistent when changing the graphics stack. Preserve the X11 socket
  directory's sticky bit and remove Selkies' `LD_PRELOAD` interposers from
  Wine's environment.
- Keep seccomp enabled. The custom profile is based on Docker's default and
  permits only the 32-bit `socket` syscall exception Wine needs; keep it aligned
  across the Compose example, direct-run documentation and smoke tests.
- Do not commit proprietary installers, credentials, Wine prefixes or runtime
  player data. Check redistribution and hosted-use terms before publishing
  images containing third-party components.

## Changes and validation

- Keep changes focused on the requested milestone; identify unresolved design
  choices rather than assuming unvalidated features or performance targets.
- Download BYOND only from the community mirror. Pin external dependencies where
  practical, preserve artifact checks and document unpinned downloads. Never
  weaken integrity checks to make builds pass.
- Keep CI and release behavior consistent: smoke-test the image that will be
  published. Cache only build-time, non-player data; invalidate cached Wine
  prefixes when their inputs change and document how to refresh them.
- Add focused tests for new behavior and failures; run the smallest relevant
  checks. Validate routing, lifecycle and isolation with integration tests,
  and real gameplay separately rather than relying on process health alone.
  Startup and health smoke tests do not establish game-scene rendering,
  WebView compatibility or playability; record manual results and unresolved
  behavior separately.
- Document configuration, trust boundaries, operational limits and manual
  verification. Report missing prerequisites and unverified compatibility
  explicitly; do not present scaffolding as production-ready.
