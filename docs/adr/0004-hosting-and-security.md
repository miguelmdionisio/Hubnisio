# ADR-0004: Hosting and security

**Status:** Accepted
**Date:** 2026-10-22
**Deciders:** Miguel Dionísio

## Context

- The hub holds a household's full financial history, and later health and fitness data.
- There is no always-on machine yet; one is planned. Development happens on a Windows PC.
- Users: one or two people, all trusted, on their own devices.
- No public audience: nothing about this app needs to be reachable from the internet.

## Decision

### Where it runs

- **Development:** Docker Compose on the dev machine (Docker Desktop): Postgres, backend API, worker, frontend dev server.
- **Production:** the same Compose stack on a self-hosted, always-on machine. Until it exists, bank syncs only run while the dev machine is on.

### Network

- Reachable only over **Tailscale**: no port forwarding, no public DNS records.
- HTTPS inside the private network via Tailscale certificates or Tailscale Serve.
- A **Caddy** reverse proxy serves the SPA and forwards `/api` to the backend.
- Postgres is never exposed outside the Docker network.

### Authentication

- App-level login even behind the VPN: **passkeys (WebAuthn)**, with httpOnly secure session cookies and CSRF protection.
- Implementation chosen at scaffold time: in-app (py_webauthn) or a self-hosted passkey OIDC provider (e.g. Pocket ID).

### Data protection

- **Full-disk encryption** on the server.
- **App-level encryption** for provider secrets (Enable Banking session IDs, the Trading 212 API key), using AES-GCM with a versioned key. The key comes from a secret file, never from the database, so rotation is possible.
- **Separate Postgres roles:** a migration owner, an app role (data access only, no DDL), and a read-only analytics role ([ADR-0006](0006-ai-access.md)).
- **Audit log** (`core.audit_log`) of data changes and of what was sent to external AI services.
- **Logging:** no transaction details or personal data at info level; tokens and keys always redacted.

### Secrets

- Never in git. `.env` files are gitignored; a committed `.env.example` documents them.
- gitleaks runs in pre-commit and in CI.
- The Enable Banking private key is mounted as a file (Docker secret), not passed as an environment variable.
- Optional: SOPS + age if encrypted secrets in the repo become useful.

### Backups

- Nightly `pg_dump` → **restic**, encrypted on the machine before upload → offsite storage (Backblaze B2 or Hetzner Storage Box).
- Retention: 7 daily, 4 weekly, 12 monthly.
- **A restore test every quarter**, written down as a runbook.
- The restic password, app encryption key and Enable Banking private key are also kept offline (password manager). Without them, the backups are useless.

### Updates

- Renovate or Dependabot for dependencies and base images.

## Options Considered

### Option A: Self-hosted at home, private network only (chosen)

| Dimension | Assessment |
|-----------|------------|
| Complexity | Medium: you are the ops team |
| Cost | Hardware once, plus electricity; Tailscale's free tier fits |
| Scalability | Plenty for a household |
| Familiarity | Docker Compose plus a few well-documented tools |

**Pros:** the data never sits on someone else's disk; no internet attack surface.
**Cons:** uptime depends on home power and network; hardware failure is on you (hence offsite backups).

### Option B: VPS (e.g. Hetzner)

**Pros:** always on, no hardware, same Compose stack.
**Cons:** the full financial history sits on a provider's disk; a public IP means hardening the host. A good fallback, and it can still be locked to Tailscale.

### Option C: Managed platforms (Supabase, Vercel, Fly.io)

**Pros:** least operations work.
**Cons:** several third parties hold the data; harder to keep off the public internet; the stack gets bent to fit each platform.

## Trade-off Analysis

For a household's complete financial and health record, data custody and attack surface outweigh convenience. A gives the smallest surface. B is the escape hatch if home hosting turns out impractical, and moving between them is a redeploy, because everything is in Compose.

## Consequences

- **Easier:** strong privacy posture; no public endpoints to harden; one stack in development and production.
- **Harder:** backups, updates and restore tests are your job; the app is only reachable from devices on the private network.
- **Revisit:** if a provider ever requires a publicly reachable webhook; the auth implementation choice at scaffold time.

## Action Items

1. [ ] Compose stack for development: Postgres, API, worker, frontend.
2. [ ] `.gitignore`, `.env.example`, gitleaks in pre-commit, from the first commit.
3. [ ] Encryption helper for provider secrets, with key versioning.
4. [ ] Postgres roles and grants in migrations.
5. [ ] When the server exists: Tailscale, Caddy, disk encryption, restic backups, first restore test.
