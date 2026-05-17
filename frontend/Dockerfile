FROM node:24-alpine@sha256:d1b3b4da11eefd5941e7f0b9cf17783fc99d9c6fc34884a665f40a06dbdfc94f AS builder
RUN corepack enable pnpm
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

FROM nginx:alpine@sha256:dc48b7a872a79fb541ba5081d320b11b549231bc63ba465a7495afaa7d2ebcb8 AS runner
COPY --from=builder /app/out /usr/share/nginx/html
EXPOSE 80
