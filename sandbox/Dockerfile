FROM debian:trixie-20260505@sha256:e2d08da6f42ef4b09b165d55528a12727aeed8240dc9edf888e3ec07e10ef9da

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

COPY --from=ghcr.io/astral-sh/uv@sha256:841c8e6fe30a8b07b4478d12d0c608cba6de66102d29d65d1cc423af86051563 /uv /usr/local/bin/uv

ENV PATH="/root/.carapace/bin:/root/.local/bin:${PATH}" \
   NODE_USE_ENV_PROXY=1
RUN uv python install 3.14 --default --preview-features python-install-default
RUN corepack enable

# Proxy setup script — reads HTTP(S)_PROXY env vars and writes per-tool
# config files so that apt, git, pip, npm etc. all route through the proxy.
COPY setup-proxy.sh /usr/local/bin/setup-proxy.sh
RUN chmod +x /usr/local/bin/setup-proxy.sh

COPY ccred /usr/local/bin/ccred
RUN chmod +x /usr/local/bin/ccred

RUN mkdir -p /root/.carapace/bin /workspace \
   && git config --global --add safe.directory /workspace

WORKDIR /workspace
