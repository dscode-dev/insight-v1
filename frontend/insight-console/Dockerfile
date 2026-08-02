# syntax=docker/dockerfile:1.7
#
# insight-console — operator console (Next.js standalone). V1.2.
#
# BUILD CONTEXT IS the repo dir (no sibling deps):
#
#   docker build -f insight-console/Dockerfile insight-console \
#     -t konohalabs/insight-console:TAG
#
# Secrets (ADMIN_API_INTERNAL_TOKEN, SESSION_SECRET) are RUNTIME env — never build args. The build uses
# placeholders only to satisfy page-data collection.

FROM node:20-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json ./
# eslint 9 vs eslint-config-next 14 peer conflict — known, pinned.
RUN npm ci --legacy-peer-deps

FROM node:20-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .
ENV NEXT_TELEMETRY_DISABLED=1
ARG NEXT_PUBLIC_BASE_PATH=/console
ENV NEXT_PUBLIC_BASE_PATH=${NEXT_PUBLIC_BASE_PATH}
# Build-time placeholder ONLY (lib/admin-api.ts asserts presence during
# page-data collection); real values come from runtime env.
RUN ADMIN_API_INTERNAL_TOKEN=build-placeholder npm run build

FROM node:20-alpine AS runtime

LABEL org.opencontainers.image.title="insight-console"
LABEL org.opencontainers.image.description="Insight Console — operations center (publication control, agents, audit)"
LABEL org.opencontainers.image.source="https://github.com/konoha-labs/insight-console"
LABEL org.opencontainers.image.licenses="proprietary"
LABEL org.opencontainers.image.vendor="Konoha Labs"

WORKDIR /app
ENV NODE_ENV=production \
    NEXT_TELEMETRY_DISABLED=1 \
    NEXT_PUBLIC_BASE_PATH=/console \
    PORT=3001 \
    HOSTNAME=0.0.0.0

RUN addgroup --system --gid 10001 insight \
 && adduser --system --uid 10001 --ingroup insight insight

COPY --from=builder --chown=insight:insight /app/.next/standalone ./
COPY --from=builder --chown=insight:insight /app/.next/static ./.next/static
# Brand assets (logo, favicon) — standalone output does not bundle public/.
COPY --from=builder --chown=insight:insight /app/public ./public

USER insight

EXPOSE 3001

CMD ["node", "server.js"]
