# syntax=docker/dockerfile:1.7
#
# insight-gateway — the single public API. V1.2 packaging.
#
# BUILD CONTEXT IS modules_v1/ (the parent dir), because go.mod path-
# replaces ../insight-runtime-go and ../insight-protos/gen/go (the old
# repo-local context could not build at all — Sprint X / V1.2 fix):
#
#   docker build -f insight-gateway/Dockerfile -t konohalabs/insight-gateway:TAG .
#
# Ships the binary + goose + migrations at /app/migrations so the
# compose one-shot `gateway-migrate` runs from the same image.

ARG GO_VERSION=1.23
ARG GOOSE_VERSION=v3.22.1
ARG DISTROLESS_REF=gcr.io/distroless/static-debian12:nonroot

FROM golang:${GO_VERSION}-alpine AS builder

WORKDIR /src

ARG INSIGHT_VERSION=dev

RUN apk add --no-cache ca-certificates git

COPY insight-runtime-go ./insight-runtime-go
COPY insight-protos/gen/go ./insight-protos/gen/go

COPY insight-gateway/go.mod insight-gateway/go.sum ./insight-gateway/

WORKDIR /src/insight-gateway

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download

WORKDIR /src

COPY insight-gateway ./insight-gateway

WORKDIR /src/insight-gateway

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath \
      -ldflags "-s -w -X main.version=${INSIGHT_VERSION}" \
      -tags netgo \
      -o /out/gateway ./cmd/gateway

ARG GOOSE_VERSION
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go install github.com/pressly/goose/v3/cmd/goose@${GOOSE_VERSION} \
 && cp "$(go env GOPATH)/bin/goose" /out/goose

FROM ${DISTROLESS_REF} AS runtime

LABEL org.opencontainers.image.title="insight-gateway"
LABEL org.opencontainers.image.description="Insight Gateway — public API: auth, uploads, social BFF"
LABEL org.opencontainers.image.source="https://github.com/konoha-labs/insight-gateway"
LABEL org.opencontainers.image.licenses="proprietary"
LABEL org.opencontainers.image.vendor="Konoha Labs"

WORKDIR /app

COPY --from=builder /out/gateway /usr/local/bin/app
COPY --from=builder /out/goose /usr/local/bin/goose
COPY --from=builder /src/insight-gateway/migrations /app/migrations
COPY --from=builder /src/insight-gateway/tools /opt/insight/tools

USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/app"]
