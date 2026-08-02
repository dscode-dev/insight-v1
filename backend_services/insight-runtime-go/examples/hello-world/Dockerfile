# Multi-stage distroless build — the template every Go service uses.
#
# Stage 1: build with full Go toolchain.
# Stage 2: copy the static binary into a nonroot distroless image.
#
# Final image is ~10–15 MB and runs as UID 65532 (nonroot).
# CGO is disabled so we get a fully static binary with zero glibc deps.

# syntax=docker/dockerfile:1.7
FROM golang:1.23 AS build
WORKDIR /src

# Cache go.mod download.
COPY go.mod go.sum* ./
RUN go mod download

COPY . .
ENV CGO_ENABLED=0
RUN go build -trimpath -ldflags='-s -w' \
    -o /out/hello-world ./examples/hello-world/cmd

FROM gcr.io/distroless/static-debian12:nonroot AS runtime
COPY --from=build /out/hello-world /usr/local/bin/app

USER nonroot:nonroot
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/app"]
