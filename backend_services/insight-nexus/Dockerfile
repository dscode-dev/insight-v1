# syntax=docker/dockerfile:1.7
#
# insight-nexus — publication engine. V1.2 packaging.
#
# BUILD CONTEXT IS modules_v1/ (the parent dir), because go.mod path-
# replaces ../insight-runtime-go and ../insight-protos/gen/go:
#
#   docker build -f insight-nexus/Dockerfile -t konohalabs/insight-nexus:TAG .
#
# Ships the service binary + nexus-migrate (idempotent SQL runner) +
# the migrations so a one-shot compose service can migrate from the
# same image.

ARG GO_VERSION=1.23

# ============================================================================
# Builder
# ============================================================================

FROM golang:${GO_VERSION}-alpine AS builder

WORKDIR /src

ARG INSIGHT_VERSION=dev

RUN apk add --no-cache ca-certificates git

# Path-replaced sibling modules.
COPY insight-runtime-go ./insight-runtime-go
COPY insight-protos/gen/go ./insight-protos/gen/go

COPY insight-nexus/go.mod insight-nexus/go.sum ./insight-nexus/

WORKDIR /src/insight-nexus

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download

WORKDIR /src

COPY insight-nexus ./insight-nexus

WORKDIR /src/insight-nexus

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath \
      -ldflags "-s -w -X main.version=${INSIGHT_VERSION}" \
      -tags netgo \
      -o /out/insight-nexus ./cmd/nexus \
 && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath -ldflags "-s -w" -tags netgo \
      -o /out/nexus-migrate ./cmd/migrate

# ============================================================================
# Runtime
# ============================================================================

FROM alpine:3.20 AS runtime

LABEL org.opencontainers.image.title="insight-nexus"
LABEL org.opencontainers.image.description="Insight Nexus — agent publication engine (trends → agents → Social)"
LABEL org.opencontainers.image.source="https://github.com/konoha-labs/insight-nexus"
LABEL org.opencontainers.image.licenses="proprietary"
LABEL org.opencontainers.image.vendor="Konoha Labs"

WORKDIR /app

RUN apk add --no-cache ca-certificates wget \
 && addgroup -S insight \
 && adduser -S -G insight -u 10001 insight

COPY --from=builder /out/insight-nexus /usr/local/bin/insight-nexus
COPY --from=builder /out/nexus-migrate /usr/local/bin/nexus-migrate
COPY --from=builder /src/insight-nexus/migrations /app/migrations

USER insight:insight

EXPOSE 8090 9090

HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8090/healthz | grep -q service_id

ENTRYPOINT ["/usr/local/bin/insight-nexus"]
