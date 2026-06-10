FROM alpine:3.24@sha256:a2d49ea686c2adfe3c992e47dc3b5e7fa6e6b5055609400dc2acaeb241c829f4

# 2026.2.0 has https://github.com/dani-garcia/vaultwarden/issues/6912
ARG BW_CLI_VERSION=2026.1.0

RUN apk add --no-cache nodejs npm ca-certificates curl \
 && npm install -g @bitwarden/cli@${BW_CLI_VERSION} \
 && npm cache clean --force \
 && rm -rf /root/.npm

COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

ENTRYPOINT ["/entrypoint.sh"]
