FROM debian:13@sha256:fac46bff2e02f51425b6e33b0e1169f55dfb053d83511ca28aa50c09fd5ed7a4

RUN apt-get update \
   && apt-get install -y --no-install-recommends tree \
   ca-certificates curl file gnupg jq git kubectl poppler-utils ripgrep \
   && mkdir -p /etc/apt/keyrings \
   && curl -fsSL https://deb.nodesource.com/gpgkey/nodesource-repo.gpg.key \
   | gpg --dearmor -o /etc/apt/keyrings/nodesource.gpg \
   && echo "deb [signed-by=/etc/apt/keyrings/nodesource.gpg] https://deb.nodesource.com/node_24.x nodistro main" \
   > /etc/apt/sources.list.d/nodesource.list \
   && apt-get update \
   && apt-get install -y --no-install-recommends nodejs \
   && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv@sha256:93b61e21202b1dab861092748e46bbd6e0e41dd84f59b9174efd2353186e1b47 /uv /usr/local/bin/uv

ENV PATH="/workspace/.carapace/bin:/root/.local/bin:${PATH}" \
   NODE_USE_ENV_PROXY=1
RUN uv python install 3.14 --default --preview-features python-install-default
RUN corepack enable

# Proxy setup script — reads HTTP(S)_PROXY env vars and writes per-tool
# config files so that apt, git, pip, npm etc. all route through the proxy.
COPY setup-proxy.sh /usr/local/bin/setup-proxy.sh
RUN chmod +x /usr/local/bin/setup-proxy.sh

COPY ccred /usr/local/bin/ccred
RUN chmod +x /usr/local/bin/ccred

RUN mkdir -p /workspace \
   && git config --global --add safe.directory /workspace

WORKDIR /workspace
