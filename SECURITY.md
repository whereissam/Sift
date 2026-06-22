# Security Policy

## Supported Versions

Sift is under active development. Security fixes land on the latest release and
the `main` branch.

| Version | Supported          |
| ------- | ------------------ |
| 0.2.x   | :white_check_mark: |
| < 0.2   | :x:                |

## Reporting a Vulnerability

Please do **not** open a public issue for security vulnerabilities — that
exposes the problem before a fix is available.

Instead, use either of these private channels:

- **GitHub Security Advisory** (preferred) — open the
  [Security tab](https://github.com/whereissam/xdownloader/security/advisories/new)
  and click **Report a vulnerability**. This keeps the discussion private until
  a fix ships.
- **Pull Request** — if you already have a fix, open a PR and note that it
  addresses a security issue. We'll coordinate disclosure from there.

You don't need to email anyone.

### What to include

- A description of the vulnerability and its impact
- Steps to reproduce (proof-of-concept, affected endpoint, or input)
- Affected version or commit
- Any suggested remediation, if you have one

### What to expect

- **Acknowledgement** within 3 business days
- An assessment and severity rating once we've reproduced the issue
- Regular updates as we work on a fix
- Credit in the release notes once the fix ships, unless you'd prefer to stay
  anonymous

## Deployment Hardening

Sift ships safe-by-default for **local, single-user** use. If you expose it on a
network, configure these first:

- **`API_KEY`** — set it to require an `X-API-Key` header on every request. With
  no key set, the API is open to anyone who can reach it. The Docker Compose
  setup now *requires* `API_KEY` because the container binds `0.0.0.0`.
- **`ENCRYPTION_KEY`** — set it so stored third-party API keys are encrypted at
  rest with a strong key. Without it, Sift falls back to a predictable key and
  logs a warning on startup.
- **`TELEGRAM_WEBHOOK_SECRET`** — required if you run the Telegram bot in webhook
  mode; incoming updates are rejected without a matching secret.
- **TLS** — terminate HTTPS at a reverse proxy. The app emits HSTS and a
  restrictive Content-Security-Policy, but does not terminate TLS itself.

## Threat Model & Scope

Sift ingests media from user-supplied URLs, runs local and remote AI models, and
exposes a FastAPI backend plus a Tauri desktop shell. Areas especially worth
scrutiny:

- **SSRF** — any path that fetches a user- or feed-supplied URL. Outbound
  fetches are routed through an allowlist-validating helper that re-checks every
  redirect hop; report any sink that bypasses it.
- **The API surface** (`/api/*`) — authentication, input validation, injection.
- **URL/media handling** — path traversal, command injection via downloaders or
  FFmpeg, unsafe filename handling.
- **Secrets handling** for third-party AI providers and API keys.
- **The Tauri desktop backend** — the embedded localhost server, its CORS
  policy, and IPC commands.
- **Webhook and Telegram bot endpoints.**

## Out of Scope

- Vulnerabilities in third-party dependencies — please report those upstream
  (we'll still bump the dependency once a patch is available).
- Issues that require physical access to a user's machine.
- Self-inflicted misconfiguration (e.g. exposing the backend on `0.0.0.0`
  without an `API_KEY`).

Thanks for helping keep Sift and its users safe.
