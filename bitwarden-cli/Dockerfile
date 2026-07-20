FROM alpine:3.24@sha256:28bd5fe8b56d1bd048e5babf5b10710ebe0bae67db86916198a6eec434943f8b

# 2026.2.0 has https://github.com/dani-garcia/vaultwarden/issues/6912
ARG BW_CLI_VERSION=2026.1.0

RUN apk add --no-cache nodejs npm ca-certificates curl \
 && npm install -g @bitwarden/cli@${BW_CLI_VERSION} \
 && npm cache clean --force \
 && rm -rf /root/.npm

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
