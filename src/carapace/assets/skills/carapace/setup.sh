#!/bin/sh
set -eu

# Activation runs with the network open, so the git install of carapace (and its
# full dependency tree) happens here. `carapace` commands later run with
# `uv run --no-sync` against this venv, so they never touch the network/proxy.
uv sync

echo "carapace CLI installed"
