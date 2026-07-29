FROM node:24-bookworm-slim AS build

WORKDIR /app
RUN corepack enable

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY apps/web/package.json apps/web/package.json
COPY packages/typescript/api-client/package.json packages/typescript/api-client/package.json
RUN corepack pnpm install --frozen-lockfile --filter @image-model-lab/web

COPY apps/web apps/web
RUN corepack pnpm --filter @image-model-lab/web build

FROM nginx:1.29-alpine

COPY apps/web/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/apps/web/dist /usr/share/nginx/html

EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=3s --retries=3 \
    CMD wget --quiet --spider http://127.0.0.1:8080/health.json || exit 1
