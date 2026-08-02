# syntax=docker/dockerfile:1.7

ARG GO_VERSION=1.23
ARG GOOSE_VERSION=v3.22.1

# ============================================================================
# Builder
# ============================================================================

FROM golang:${GO_VERSION}-alpine AS builder

WORKDIR /src

ARG INSIGHT_VERSION=dev

RUN apk add --no-cache \
    ca-certificates \
    git

# ---------------------------------------------------------------------------
# Runtime module required by:
#
# replace github.com/konoha-labs/insight-runtime-go => ../insight-runtime-go
#
# Final layout:
#
# /src
# ├── insight-runtime-go
# └── insight-sport-hub
# ---------------------------------------------------------------------------

COPY insight-runtime-go ./insight-runtime-go
COPY insight-protos/gen/go ./insight-protos/gen/go

COPY insight-sport-hub/go.mod \
     insight-sport-hub/go.sum \
     ./insight-sport-hub/

WORKDIR /src/insight-sport-hub

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download

WORKDIR /src

COPY insight-sport-hub ./insight-sport-hub

WORKDIR /src/insight-sport-hub

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64 \
    go build \
      -trimpath \
      -ldflags "-s -w -X main.version=${INSIGHT_VERSION}" \
      -tags netgo \
      -o /out/insight-sports-hub \
      ./cmd/sportshub

ARG GOOSE_VERSION

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 \
    GOOS=linux \
    GOARCH=amd64 \
    go install github.com/pressly/goose/v3/cmd/goose@${GOOSE_VERSION}

RUN cp "$(go env GOPATH)/bin/goose" /out/goose

# ============================================================================
# Runtime
# ============================================================================

FROM alpine:3.20 AS runtime

LABEL org.opencontainers.image.title="insight-sports-hub"
LABEL org.opencontainers.image.description="Insight Sports Data Hub — ingestion + canonical pipeline"
LABEL org.opencontainers.image.source="https://github.com/konoha-labs/insight"
LABEL org.opencontainers.image.licenses="proprietary"
LABEL org.opencontainers.image.vendor="Konoha Labs"

WORKDIR /app

RUN apk add --no-cache ca-certificates wget \
 && addgroup -S insight \
 && adduser -S -G insight -u 10001 insight

COPY --from=builder /out/insight-sports-hub /usr/local/bin/insight-sports-hub
COPY --from=builder /out/goose /usr/local/bin/goose

# Copia migrations geradas no builder
COPY --from=builder /src/insight-sport-hub/migrations /app/migrations

USER insight:insight

EXPOSE 8080 9080

HEALTHCHECK --interval=20s --timeout=3s --start-period=20s --retries=3 \
  CMD wget -qO- http://127.0.0.1:8080/healthz | grep -q ok

ENTRYPOINT ["/usr/local/bin/insight-sports-hub"]
