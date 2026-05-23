FROM node:24-alpine@sha256:2bdb65ed1dab192432bc31c95f94155ca5ad7fc1392fb7eb7526ab682fa5bf14 AS builder
RUN corepack enable pnpm
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile
COPY . .
RUN pnpm run build

FROM nginx:alpine@sha256:7e8ff0a32da368869608f285124b4375b901401d88f5027865d8f88984d35d38 AS runner
COPY --from=builder /app/out /usr/share/nginx/html
EXPOSE 80
