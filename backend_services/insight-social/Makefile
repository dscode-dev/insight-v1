# insight-social — developer Makefile.
#
# Same target shape as insight-gateway so muscle memory transfers
# across the polyrepo. Production never invokes `make`; CI calls the
# underlying `go`/`docker`/`kubectl` commands directly.

SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

SERVICE      := insight-social
GO_PKGS      := ./...
DOCKER_IMAGE ?= konoha-labs/$(SERVICE)
DOCKER_TAG   ?= dev
GOOSE_DIR    := migrations
GOOSE_DRIVER := postgres

# DATABASE_URL is required by every db-* target — fail fast if missing.
require-db:
	@[ -n "$$DATABASE_URL" ] || (echo "DATABASE_URL is required" >&2; exit 1)

# ---- run / build ----
.PHONY: run
run:
	go run ./cmd/social

.PHONY: build
build:
	CGO_ENABLED=0 go build -trimpath -o bin/$(SERVICE) ./cmd/social

# ---- quality gates ----
.PHONY: test
test:
	go test -race -count=1 $(GO_PKGS)

.PHONY: lint
lint:
	@if ! command -v golangci-lint >/dev/null; then \
		echo "golangci-lint not installed (brew install golangci-lint)"; exit 1; \
	fi
	golangci-lint run $(GO_PKGS)

.PHONY: tidy
tidy:
	go mod tidy

# ---- db (goose) ----
# Always runs against $DATABASE_URL — same env contract as the binary.
.PHONY: db-status
db-status: require-db
	goose -dir $(GOOSE_DIR) $(GOOSE_DRIVER) "$$DATABASE_URL" status

.PHONY: db-up
db-up: require-db
	goose -dir $(GOOSE_DIR) $(GOOSE_DRIVER) "$$DATABASE_URL" up

.PHONY: db-down
db-down: require-db
	goose -dir $(GOOSE_DIR) $(GOOSE_DRIVER) "$$DATABASE_URL" down

.PHONY: db-cutover
db-cutover: require-db
	./tools/seed_goose_marker.sh

# ---- docker ----
.PHONY: docker-build
docker-build:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

.PHONY: docker-run
docker-run:
	docker run --rm -p 50051:50051 -p 8080:8080 \
		--env-file .env \
		$(DOCKER_IMAGE):$(DOCKER_TAG)

# ---- k8s ----
# Lints the local-lab + production overlays. Production runs through
# kustomize so we catch typos before they hit Argo.
.PHONY: k8s-lint
k8s-lint:
	@for overlay in k8s/overlays/local-lab k8s/overlays/production; do \
		echo ">>> kustomize build $$overlay"; \
		kubectl kustomize $$overlay >/dev/null; \
	done
