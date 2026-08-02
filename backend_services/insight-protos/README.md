# insight-protos

Single source of truth for every gRPC contract across the Insight
platform. Both Go services (gateway, social, sports, campaign, admin,
analytics) and Python services (atlas) consume generated stubs
from this repo.

## Layout

```
proto/
├── social/v1/      Social Domain (user, community, signal, ...)
├── sports/v1/      Sports Data Hub (match, competition, team)
├── campaign/v1/    Campaign Service (campaign, placement, analytics)
├── admin/v1/       Admin Platform (health, moderation, audit, source)
├── analytics/v1/   Analytics Layer (timeline queries)
├── atlas/v1/       Atlas ML — gRPC shell over the Python core
└── pundit/v1/      DEPRECATED — Pundit retired (superseded by the trend
                    stream + Nexus); removal candidate, see RUNTIME_PROTO_AUDIT.md
```

Every package is **versioned in its directory**. Breaking changes
require a `v2/` directory alongside; `v1/` keeps shipping until every
consumer cuts over.

## Tooling

* `buf` — lint, breaking-change detection, code generation.
* CI publishes generated artifacts on every tagged release:
  * Go: `github.com/konoha-labs/insight-protos/gen/go@v1.x.x`
  * Python: `insight_protos_pb-1.x.x` wheel

## Consumer setup

### Go

```go
require github.com/konoha-labs/insight-protos/gen/go v1.0.0
```

```go
import socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
```

### Python

```bash
pip install insight-protos-pb==1.0.0
```

```python
from insight_protos_pb.social.v1 import user_pb2, user_pb2_grpc
```

## Local development

```bash
# Lint
buf lint

# Breaking-change check vs main
buf breaking --against '.git#branch=main'

# Generate (writes to gen/go + gen/py)
buf generate
```

Generated code is **not committed** — CI publishes the artifacts on
release. Developers iterating locally can either run `buf generate`
into a workspace or path-install from a sibling clone.

## Versioning rules

* Anything inside `<service>/v1/` is locked at v1.
* Field-number deletions are forbidden by `buf breaking`.
* Renames are breaking — bump the package directory.
* New optional fields are non-breaking and OK on patch releases.
* Removing an RPC is breaking — deprecate first, then remove in a v2.

## Release process

1. Open PR with changes; `buf lint` and `buf breaking` run in CI.
2. Merge to `main`.
3. Tag `v1.x.y` (semver per package directory).
4. CI generates artifacts and publishes:
   * Go module pushed via `gopkg.in/...`-style indirection (or commit
     into a `release/v1.x.y` branch for direct import path).
   * Python wheel uploaded to internal PyPI / shared release.
