SHELL := /usr/bin/env bash
.SHELLFLAGS := -eu -o pipefail -c

SERVICE      := insight-sports-hub
GO_PKGS      := ./...
DOCKER_IMAGE ?= konoha-labs/$(SERVICE)
DOCKER_TAG   ?= dev
GOOSE_DIR    := migrations
GOOSE_DRIVER := postgres

require-db:
	@[ -n "$$DATABASE_URL" ] || (echo "DATABASE_URL is required" >&2; exit 1)

.PHONY: run
run:
	go run ./cmd/sportshub

.PHONY: build
build:
	CGO_ENABLED=0 go build -trimpath -o bin/$(SERVICE) ./cmd/sportshub

.PHONY: test
test:
	go test -race -count=1 $(GO_PKGS)

.PHONY: lint
lint:
	@if ! command -v golangci-lint >/dev/null; then \
		echo "golangci-lint not installed"; exit 1; \
	fi
	golangci-lint run $(GO_PKGS)

.PHONY: tidy
tidy:
	go mod tidy

# ---- db (goose) ----
.PHONY: db-status
db-status: require-db
	goose -dir $(GOOSE_DIR) $(GOOSE_DRIVER) "$$DATABASE_URL" status

.PHONY: db-up
db-up: require-db
	goose -dir $(GOOSE_DIR) $(GOOSE_DRIVER) "$$DATABASE_URL" up

.PHONY: db-down
db-down: require-db
	goose -dir $(GOOSE_DIR) $(GOOSE_DRIVER) "$$DATABASE_URL" down

# ---- docker ----
.PHONY: docker-build
docker-build:
	docker build -t $(DOCKER_IMAGE):$(DOCKER_TAG) .

# ---- k8s ----
.PHONY: k8s-lint
k8s-lint:
	@for overlay in k8s/overlays/local-lab k8s/overlays/production; do \
		echo ">>> kustomize build $$overlay"; \
		kubectl kustomize $$overlay >/dev/null; \
	done
