# syntax=docker/dockerfile:1.7
#
# insight-social — distroless multi-stage build. V1.2 packaging.
#
# BUILD CONTEXT IS modules_v1/ (the parent dir), because go.mod path-
# replaces ../insight-runtime-go and ../insight-protos/gen/go:
#
#   docker build -f insight-social/Dockerfile -t konohalabs/insight-social:TAG .
#
# Ships the binary + goose + migrations at /app/migrations so the
# compose one-shot `social-migrate` runs from the same image.

ARG GO_VERSION=1.23
ARG GOOSE_VERSION=v3.22.1
ARG DISTROLESS_REF=gcr.io/distroless/static-debian12:nonroot

FROM golang:${GO_VERSION}-alpine AS builder

WORKDIR /src

ARG INSIGHT_VERSION=dev

RUN apk add --no-cache ca-certificates git

COPY insight-runtime-go ./insight-runtime-go
COPY insight-protos/gen/go ./insight-protos/gen/go

COPY ./insight-social/go.mod ./insight-social/go.sum ./insight-social/

WORKDIR /src/insight-social

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    go mod download

WORKDIR /src

COPY ./insight-social ./insight-social

WORKDIR /src/insight-social

RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go build -trimpath \
      -ldflags "-s -w -X main.version=${INSIGHT_VERSION}" \
      -tags netgo \
      -o /out/insight-social ./cmd/social

ARG GOOSE_VERSION
RUN --mount=type=cache,target=/go/pkg/mod \
    --mount=type=cache,target=/root/.cache/go-build \
    CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
    go install github.com/pressly/goose/v3/cmd/goose@${GOOSE_VERSION} \
 && cp "$(go env GOPATH)/bin/goose" /out/goose

FROM ${DISTROLESS_REF} AS runtime

LABEL org.opencontainers.image.title="insight-social"
LABEL org.opencontainers.image.description="Insight Social — social graph, posts, query-time feeds (gRPC, internal-only)"
LABEL org.opencontainers.image.source="https://github.com/konoha-labs/insight-social"
LABEL org.opencontainers.image.licenses="proprietary"
LABEL org.opencontainers.image.vendor="Konoha Labs"

WORKDIR /app

COPY --from=builder /out/insight-social /usr/local/bin/insight-social
COPY --from=builder /out/goose          /usr/local/bin/goose
COPY --from=builder /src/insight-social/migrations /app/migrations

USER nonroot:nonroot

# gRPC + HTTP (health/metrics).
EXPOSE 50051 8080

ENTRYPOINT ["/usr/local/bin/insight-social"]
