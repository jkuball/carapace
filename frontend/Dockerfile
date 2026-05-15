FROM node:24-alpine@sha256:d1b3b4da11eefd5941e7f0b9cf17783fc99d9c6fc34884a665f40a06dbdfc94f AS builder
RUN corepack enable pnpm
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

FROM nginx:alpine@sha256:feb6f75a08aa55b44576f98c15b8859819ecf54f3e4d2157f42c2d01cb58a3d2 AS runner
COPY --from=builder /app/out /usr/share/nginx/html
EXPOSE 80
