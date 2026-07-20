---
name: ksf-security
description: Use when changing KSF secrets, permissions, OAuth2 Proxy, CrowdSec, Traefik, DNS, host ports, Docker socket access, webui mutations, or untrusted input.
---

# KSF Security

- Keep secrets out of Git, images, logs, and error output; secret files use mode
  `600`.
- Validate and bound all CLI and API input, including paths, instances, hosts,
  ports, URLs, and provider responses.
- Do not expose a service publicly outside Traefik. Published app ports bind to
  `127.0.0.1` only.
- OAuth2 Proxy authenticates users; KSF applications still enforce their own
  authorization decisions where required.
- Trust identity headers only behind the configured proxy boundary.
- Treat the writable Docker socket and KSF runtime mount used by webui as an
  administrative trust boundary; preserve host UID/GID ownership.
- Confirm destructive operations and log them without secrets.
