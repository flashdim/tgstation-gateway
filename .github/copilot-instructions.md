# Project guidance

tgstation-gateway aims to run the standard BYOND Windows client in a
browser-accessible, isolated per-player container. The initial Dockerfile is
an experimental single-player image, not a production multi-user gateway.

## Architecture

- Keep the game server and tgstation-server separate from client sessions.
- Use Wine and the real BYOND client; do not reimplement the BYOND protocol.
- Future session management should create, route, limit and clean up one
  container per player. Traefik is expected to provide HTTPS and delegate
  authentication, but authorization must verify ownership of each session,
  including streaming connections.
- Never expose the Docker API or a player's session directly to other players.
  Treat credentials, Wine prefixes, the desktop, forwarded identity headers and
  user-provided URLs as sensitive or untrusted.
- BYOND may see shared IP addresses or computer IDs. Preserve ban enforcement
  and investigate collisions instead of silently bypassing checks.
- Do not commit proprietary installers, credentials, Wine prefixes or runtime
  player data. Check redistribution and hosted-use terms before publishing
  images containing third-party components.

## Changes and validation

- Keep the single-player image usable independently of any future manager.
- Pin external dependencies where practical; verify downloaded artifacts and
  do not disable integrity checks to make builds pass.
- Document build, configuration, security limitations and manual verification.
- Test actual behavior where possible. Clearly report missing prerequisites,
  unverified compatibility or unsupported deployment modes; do not present
  scaffolding as production-ready.
