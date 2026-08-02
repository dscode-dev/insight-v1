# insight-runtime-go

Shared Go runtime library imported by every Insight Go service
(gateway, social, sports, campaign, admin, analytics).

## What's in here

```
pkg/
├── logging/         zerolog setup + trace-aware FromContext()
├── tracing/         OpenTelemetry SDK init + OTLP exporter
├── metrics/         Prometheus registry + /metrics handler
├── health/          /healthz + /readyz with concurrent probes
├── middleware/      RequestID, Recovery, BodyLimit, SecurityHeaders
├── grpcclient/      Dial helper with mTLS + OTel + keepalive
├── grpcserver/      Server helper with interceptors + optional mTLS
└── config/          Typed env parsers (MustString/Int/Bool/Float)
```

Plus `examples/hello-world/` — a runnable service that wires the whole
stack. It's both the smoke test for the foundation and the template the
service scaffolder copies into new repos.

## Why a separate lib

* Every service repeats the same `main.go` plumbing (logging, tracing,
  health, graceful shutdown). Lifting it here keeps service `main`s
  short (~80 lines).
* CI/CD upgrades land in one place. Bumping an OTel SDK or a
  Prometheus client version is a single PR + ripple to consumers.
* Cross-service log/trace conventions stay enforced — every service
  logs the same JSON schema because they import the same `logging.Init`.

## Versioning

* Semver. Breaking API changes bump the major.
* Consumers pin in their `go.mod`:
  `require github.com/konoha-labs/insight-runtime-go v1.x.y`
* Backwards-compat: new packages = minor bump; new constructor
  arguments = use option structs to keep additive.

## Local development

```bash
# Tidy + verify
go mod tidy
go vet ./...

# Run the hello-world example
go run ./examples/hello-world/cmd

# In another terminal
curl localhost:8080/
curl localhost:8080/healthz
curl localhost:8080/readyz
curl localhost:8080/metrics
```

## Smoke test against the foundation (W0.7)

When cert-manager + OTel Collector + external-secrets are deployed in
the lab cluster (Phase 4 sprint 1 mid-point), build + push the
hello-world image and apply the K8s manifest in
`examples/hello-world/k8s/`. Confirms end-to-end:

* mTLS cert issued and mounted
* Spans flowing into the OTel Collector
* `/metrics` scraped by Prometheus
* Secret synthesised from Vault via external-secrets-operator

## Contribution rules

* No business logic. This lib is infrastructure-only.
* No service-specific helpers. Anything that touches the social
  domain or a specific table belongs in the service repo.
* Tests required for any package that grows past 50 lines.
