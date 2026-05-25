# Quickstart

This guide walks you through deploying carapace with Docker Compose. For Kubernetes, see the [Helm chart README](../charts/carapace/README.md).

## Prerequisites

- **Docker** with the Compose plugin
- An **Anthropic API key** (or Google API key if using Gemini models)

## 1. Create your `.env`

```bash
cp .env.example .env
```

Fill in the required values:

```env
# Required
ANTHROPIC_API_KEY=sk-ant-...
CARAPACE_TOKEN=pick-a-bootstrap-admin-password

# Optional — uncomment if needed
# GOOGLE_API_KEY=...
# CARAPACE_MATRIX_PASSWORD=...
# CARAPACE_GIT_TOKEN=...
```

If no `admin` user exists yet, `CARAPACE_TOKEN` becomes that user's initial password and must be at least 16 characters long. After startup, normal web UI, CLI, REST, WebSocket, and admin access uses username/password login and an HttpOnly session cookie.

## 2. Build and start

```bash
docker compose build
docker compose up -d
```

This starts:

- **Server** at `http://localhost:8321`
- **Frontend** at `http://localhost:3001`
- **Redis** for mandatory session-list caching
- **Sandbox image** is built automatically

Log in to the web UI as `admin` with the `CARAPACE_TOKEN` value, then open **Settings** → **Admin** → **Users** to create your normal user. You can also use the admin API after logging in and storing the session cookie:

```bash
curl -c carapace.cookies -X POST http://localhost:8321/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"'"$CARAPACE_TOKEN"'"}'

curl -X POST http://localhost:8321/api/admin/users \
  -b carapace.cookies \
  -H "Content-Type: application/json" \
  -d '{"username":"thies","password":"change-me","display_name":"Thies"}'
```

The web UI prompts for the server URL, username, and password on first connect.

See [auth.md](auth.md) for the full user-file format, admin API, and session-cookie behavior.

## 3. Connect via CLI (optional)

```bash
uv run carapace --user thies --password change-me
```

You can also set `CARAPACE_USER` and `CARAPACE_PASSWORD` for the CLI.

## 4. Configure `data/config.yaml`

The server reads its configuration from `data/config.yaml`. On first start, carapace seeds runtime files under `data/` and a separate Git-backed knowledge repo under `data/knowledge/` by default. You can customise the config at any time — restart the server to pick up changes.

A minimal config:

```yaml
agent:
  model: anthropic:claude-sonnet-4-6
  sentinel_model: anthropic:claude-haiku-4-5
  # Optional defaults for every new session.
  # Omit a field, or set it to 0, to keep that budget unlimited.
  # default_session_budget:
  #   input_tokens: 100000
  #   output_tokens: 50000
  #   cost_usd: 5.00

sessions:
  commit:
    enabled: true
    # Histories are written to data/knowledge/sessions/YYYY/MM/<session_id>/conversation.json
    path_prefix: sessions
    autosave_enabled: true
    autosave_inactivity_hours: 4
    # When true, deleting a session also removes its current committed snapshot from the knowledge repo.
    delete_from_knowledge_on_session_delete: true

cache:
  # Override this only if Redis is not reachable at the default URL.
  redis_url: redis://redis:6379/0
```

Session histories always live primarily under `data/sessions/<session_id>/`. The `sessions.commit.*` settings control a secondary commit flow into the Git-backed knowledge repo so the agent can refer back to past conversations later.

The knowledge repo location is configurable via `knowledge_dir` in `config.yaml`. If you do not override it, the default path is `data/knowledge/` because `knowledge_dir` defaults to `./knowledge` relative to the config file.

In the web UI, public sessions expose a "Commit to knowledge" action. Private sessions do not. Autosave uses the same privacy rule: only public, inactive sessions are eligible.

### Optional: enable notification delivery backend

Full backend behavior and API details live in [notifications.md](notifications.md).

carapace can auto-generate a VAPID keypair on startup and reuse it from `data/notifications/vapid_private_key.pem` if you do not configure one explicitly.

```yaml
notifications:
  enabled: true
  presence_ttl_seconds: 60
  subscription_ttl_days: 30
  # Optional. If omitted, carapace generates and persists a private key automatically.
  # vapid_private_key: "<private-key-pem>"
  # Optional. Defaults to "mailto:carapace@localhost".
  # vapid_subject: "mailto:you@example.com"
  send_timeout_seconds: 10
  retry_attempts: 2
  retry_backoff_seconds: 1.0
  max_payload_bytes: 4096
  delivery_ttl_seconds: 600
  default_preferences:
    escalation_pending: true
    attended_turn_completed: true
    unattended_turn_completed: false
    unattended_turn_failed: true
```

Notes:

- If `vapid_private_key` is omitted, carapace generates one on startup and reuses it from `data/notifications/vapid_private_key.pem` on later restarts.
- If `vapid_subject` is omitted, carapace uses `mailto:carapace@localhost`.
- The public key is derived from the private key and exposed through `/api/config/vapid-public-key`.
- Delivery also requires at least one client subscription registered through the `/api/notifications/*` endpoints.
- Notification subscriptions are grouped by the authenticated username. Legacy `owner_key` values still parse for older files.

## 5. Upgrade an existing single-user data directory

If you already have data from a pre-user-auth version, assign it to a stable username before normal use:

```bash
uv run carapace upgrade-data --user thies --data-dir data
```

The upgrade command adds ownership metadata to sessions, jobs, and notifications, moves `data/knowledge` to `data/knowledges/thies`, and converts Matrix/sandbox token JSON files to YAML with `user` fields. It creates a disabled placeholder user when needed; set a password through the admin UI or admin API before logging in.

## 6. Connect Matrix (optional)

Create a Matrix account for carapace on your homeserver, then add to `data/config.yaml`:

```yaml
channels:
  matrix:
    enabled: true
    homeserver: https://matrix.example.com
    user_id: "@carapace:example.com"
    password:
      env: CARAPACE_MATRIX_PASSWORD
    allowed_rooms:
      - "!roomid:example.com"
    allowed_users:
      - "@you:example.com"
```

Set `CARAPACE_MATRIX_PASSWORD` in your `.env` and restart. carapace will join the allowed rooms and respond to messages from allowed users. Sessions are created per-room.

`allowed_rooms` and `allowed_users` are mandatory — without them the bot ignores all messages. This prevents accidental exposure if someone invites the bot to a public room.

## 7. Set up credentials

carapace can fetch credentials from a password manager on demand. The agent does not have blanket access — every credential request is evaluated by the sentinel agent and requires explicit user approval the first time it is used in a session. Credentials are intended to be consumed inside the sandbox (auto-injected via skill config or fetched with `ccred`) and must never be echoed or logged. Two backends are available.

### File backend (simple)

Create a `.env`-format secrets file:

```bash
echo "github-token=ghp_xxxxxxxxxxxx" > data/secrets.env
echo "smtp-password=myapppassword" >> data/secrets.env
```

Add to `data/config.yaml`:

```yaml
credentials:
  backends:
    dev:
      type: file
      # path defaults to <data_dir>/secrets.env
```

Credentials are accessible as `dev/github-token`, `dev/smtp-password`, etc.

### Bitwarden / Vaultwarden backend (optional)

This uses a `bw serve` sidecar container that shares the server's network namespace. carapace never sees your vault credentials — they stay in the sidecar.

1. Add your Bitwarden credentials to `.env`:

```env
# Optional. Empty means US cloud; the sidecar applies that once via `bw config server bitwarden.com`,
# records it under $BW_DATA_DIR/carapace-state/ (Compose mounts a named volume on /var/lib/bitwarden-cli), and only
# runs logout + `bw config server` again if you change this value. EU / self-hosted: set explicitly.
# BW_SERVER_URL=

BW_EMAIL=you@example.com
BW_CLIENTID=user.xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
BW_CLIENTSECRET=xxxxxxxxxxxxxxxxxxxx
BW_MASTER_PASSWORD=your-master-password
```

`BW_EMAIL` is required when using password login (no API key). `BW_CLIENTID` and `BW_CLIENTSECRET` are API keys generated in the Bitwarden web UI (Account Settings → Keys). Use them if your account has 2FA — password-only login would prompt for a TOTP code, which cannot work non-interactively in the sidecar.

If the logs show password login but you intended API key login, both `BW_CLIENTID` and `BW_CLIENTSECRET` must be non-empty in the environment Compose sees (check `.env` spelling and that variables are not commented out).

Self-hosted **Vaultwarden** must be new enough for your **Bitwarden CLI** version. If `bw login` throws `TypeError: ... toWrappedAccountCryptographicState`, upgrade Vaultwarden (see [vaultwarden#6912](https://github.com/dani-garcia/vaultwarden/issues/6912)) or pin an older `@bitwarden/cli` in `bitwarden-cli/Dockerfile`.

2. Start the sidecar:

```bash
docker compose up -d --scale bw=1
```

Startup messages from the entrypoint go to the **`bw` container** — use `docker compose logs -f bw` (not only `carapace`). Without a TTY, stdout is often block-buffered and lines can appear late or only after exit; this stack allocates a TTY for `bw` and logs progress to stderr so `docker compose logs` shows them as they run. The `bitwarden-cli-data` volume keeps Bitwarden CLI login/device state and the cached server URL across container recreation; removing that volume applies `BW_SERVER_URL` from scratch on the next start.

3. Add to `data/config.yaml`:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      # url defaults to http://127.0.0.1:8087
```

Credentials are accessible by their Bitwarden UUID: `personal/9742101e-68b8-4a07-b5b1-...`. Look up UUIDs in the Bitwarden web UI or via `bw list items`.

### Exposure control

By default, all credentials in a backend are accessible (subject to sentinel + user approval). To restrict which credentials carapace can see:

```yaml
credentials:
  backends:
    personal:
      type: bitwarden
      expose: # allowlist — only these UUIDs are accessible
        - "9742101e-68b8-4a07-b5b1-9578b5f88e6f"
        - "a1b2c3d4-e5f6-7890-abcd-ef1234567890"
      # OR:
      # hide:  # blocklist — these UUIDs are excluded
      #   - "deadbeef-..."
```

## 8. Personalise

Edit the workspace files in the knowledge repo to shape carapace's behaviour. With the default config, these live under `data/knowledge/`:

| File          | Purpose                                                   |
| ------------- | --------------------------------------------------------- |
| `SOUL.md`     | Agent personality and communication style                 |
| `USER.md`     | Information about you (name, preferences, context)        |
| `SECURITY.md` | Natural-language security policy (sentinel system prompt) |
| `AGENTS.md`   | Agent behavioural guide                                   |

## Next steps

- Install skills into `data/knowledge/skills/` by default, or into your configured `knowledge_dir` — see [docs/skills.md](skills.md)
- Explore the [architecture](architecture.md) and [security model](security.md)
- Explore [jobs.md](jobs.md) for scheduled and on-demand job runs
- Deploy to Kubernetes with the [Helm chart](../charts/carapace/README.md)
