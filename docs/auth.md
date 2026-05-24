# Authentication

carapace uses file-backed users and HttpOnly session cookies for the normal web, CLI, REST, and WebSocket API. The old `CARAPACE_TOKEN` bearer token is no longer accepted by normal app endpoints. It remains an admin/bootstrap token for user management only.

## Files

Auth state lives under `$CARAPACE_DATA_DIR/auth/`:

| File             | Purpose                                                                |
| ---------------- | ---------------------------------------------------------------------- |
| `users.yaml`     | Stable local users, password hashes, roles, and user config references |
| `sessions.yaml`  | Server-side session records used for logout and revocation             |
| `session_secret` | HMAC signing secret for browser/CLI session JWT cookies                |

One `users.yaml` entry looks like this:

```yaml
version: 1
users:
  thies:
    password_hash: "$argon2id$v=19$..."
    enabled: true
    token_version: 1
    display_name: Thies
    email: thies@example.com
    roles: []
    created_at: "2026-05-24T12:00:00Z"
    updated_at: "2026-05-24T12:00:00Z"
    password_changed_at: "2026-05-24T12:00:00Z"
    last_login_at: null
    config:
      credentials: {}
      channels:
        matrix:
          enabled: false
      git: {}
      default_models:
        agent: anthropic:claude-sonnet-4-6
        sentinel: anthropic:claude-haiku-4-5
        title: anthropic:claude-haiku-4-5
      budgets: {}
```

Usernames are normalized to lowercase and should be stable, hand-picked names for the self-hosted users of an instance.

## Creating Users

Set `CARAPACE_TOKEN` to a random admin token in the server environment, start the server, then create users through the admin API:

```bash
curl -X POST http://localhost:8321/api/admin/users \
  -H "Authorization: Bearer $CARAPACE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username":"thies","password":"change-me","display_name":"Thies"}'
```

The web UI logs in with username and password. The CLI does the same:

```bash
uv run carapace --user thies --password change-me
```

You can also set `CARAPACE_USER` and `CARAPACE_PASSWORD` for the CLI.

## Session Cookies

`POST /api/auth/login` verifies the password, creates a server-side session in `auth/sessions.yaml`, and sets the `carapace_session` HttpOnly cookie. The cookie contains a signed JWT with the username, session id, expiry, and token version. The server still checks the session file and user record on every request, so logout and disabled users take effect without waiting for cookie expiry.

`POST /api/auth/logout` revokes the server-side session and deletes the cookie.

Changing a password increments `token_version`, which invalidates older cookies for that user.

## Owned Data

User ownership is stored close to existing runtime files instead of changing the main directory structure:

- `sessions/<session_id>/meta.yaml` contains `user: <username>`.
- `jobs.yaml` job entries contain optional `user`.
- notification subscription YAML files contain optional `user`.
- legacy records without a user still parse, but authenticated app APIs hide them until migration assigns an owner.

The knowledge repo migration moves `data/knowledge` to `data/knowledges/<username>`. Runtime use of per-user knowledge directories is tracked separately from this first auth/storage migration.

## Upgrading Existing Data

For an existing single-user instance, run:

```bash
uv run carapace upgrade-data --user thies --data-dir data
```

This creates a disabled placeholder user if needed, adds ownership metadata to sessions/jobs/notifications, moves `knowledge` to `knowledges/<user>`, and converts `matrix_token.json` and `sandbox_tokens.json` to YAML files with user fields. Set a real password through the admin API before using that user for normal login.
