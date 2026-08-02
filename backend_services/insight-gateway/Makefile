# insight-gateway operator commands.
#
# All targets are intentionally thin wrappers — heavy lifting lives in
# the workflow yml (CI) or the K8s overlays (deploys).

SHELL := /usr/bin/env bash

# --- Local dev ---

.PHONY: run
run: ## Run the gateway locally against the lab cluster's downstream
	go run ./cmd/gateway

.PHONY: build
build: ## Build the binary into ./bin/gateway
	@mkdir -p bin
	CGO_ENABLED=0 go build -trimpath -ldflags='-s -w' -o bin/gateway ./cmd/gateway

.PHONY: test
test: ## Run unit tests with race detector
	go test -race -coverprofile=cover.out -covermode=atomic ./...

.PHONY: lint
lint: ## Run golangci-lint (install separately: brew install golangci-lint)
	golangci-lint run ./...

.PHONY: tidy
tidy:
	go mod tidy

# --- Migrations ---
# Uses goose: `go install github.com/pressly/goose/v3/cmd/goose@latest`.

.PHONY: db-status
db-status: ## Show current schema_migrations state
	goose -dir migrations postgres "$$DATABASE_URL" status

.PHONY: db-up
db-up: ## Apply all pending migrations
	goose -dir migrations postgres "$$DATABASE_URL" up

.PHONY: db-down
db-down: ## Roll back the most recent migration
	goose -dir migrations postgres "$$DATABASE_URL" down

.PHONY: db-seed-marker
db-seed-marker: ## One-shot cutover: mark alembic-applied migrations as goose-applied
	bash tools/seed_goose_marker.sh

# --- Docker ---

IMAGE_TAG ?= dev

.PHONY: docker-build
docker-build: ## Build the distroless image
	cd .. && docker build -f insight-gateway/Dockerfile \
	  -t konohalabs/insight-gateway:$(IMAGE_TAG) .

.PHONY: docker-run
docker-run: ## Run the image locally; expects env file at .env.local
	docker run --rm -p 8080:8080 --env-file .env.local \
	  konohalabs/insight-gateway:$(IMAGE_TAG)

# --- K8s ---

.PHONY: k8s-lint
k8s-lint:
	kubectl kustomize k8s/overlays/local-lab > /dev/null
	kubectl kustomize k8s/overlays/production > /dev/null
	@echo "manifests valid"

.PHONY: help
help:
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)
