#!/usr/bin/env python3
"""Assemble the carapace OAuth state blob for a skill's MCP server.

Prints a compact, single-line JSON object to paste into the vault entry that a
skill's `mcp[].auth.vault_path` (type: oauth) points at. carapace refreshes the
access token from `refresh_token` on first use and writes the rotated blob back,
so `access_token` / `expires_at` are optional here — you only need the endpoint,
client id, and a valid refresh token.

Obtain `refresh_token` out-of-band via the provider's one-time OAuth login
(e.g. `mcp2cli --oauth ... --login` then read its token cache, or the provider
console). See docs/skills.md.

    python scripts/mcp_oauth_blob.py \
        --token-url https://<issuer>/oauth2/token \
        --client-id <id> [--client-secret <secret>] \
        --refresh-token <token> [--scope "a b"]
"""

from __future__ import annotations

import argparse
import json
import sys


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--token-url", required=True, help="OAuth token endpoint")
    p.add_argument("--client-id", required=True)
    p.add_argument("--client-secret", default=None, help="Omit for public (PKCE) clients")
    p.add_argument("--refresh-token", required=True)
    p.add_argument("--scope", default=None)
    ns = p.parse_args()

    blob: dict[str, str] = {
        "token_url": ns.token_url,
        "client_id": ns.client_id,
        "refresh_token": ns.refresh_token,
    }
    if ns.client_secret:
        blob["client_secret"] = ns.client_secret
    if ns.scope:
        blob["scope"] = ns.scope

    sys.stdout.write(json.dumps(blob, separators=(",", ":")) + "\n")


if __name__ == "__main__":
    main()
