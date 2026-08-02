# Gateway Social Audit — Sprint 2.5 (Part 1) + Security Review (Part 14)

Date: 2026-06-12.

## Architecture as found (pre-sprint)

| Concern | Pattern | Where |
|---|---|---|
| Routing | chi via the Strangler router (STANDALONE by default since Consolidation Sprint 0; unmatched → 404). New routes register `strangler.Native(method, pattern, handler)` | `internal/interfaces/proxy` |
| Auth | `authmw.Require(tokenCodec)` middleware: Bearer JWT → user id in request context (`authmw.UserID`). SSE uses `access_token` query param (EventSource constraint) | `internal/interfaces/http/authmw`, `httprealtime/sse.go` |
| BFF style | One `Handlers` struct per surface holding gRPC clients + an upstream timeout; thin orchestration + DTO shaping, **no business logic** | `internal/interfaces/http/social/server.go` |
| gRPC client | `socialclient.Client` — one dialed conn, round-robin LB, keepalive, 8MiB recv cap, mTLS-capable | `internal/infrastructure/socialclient` |
| Error mapping | `writeGrpcError`: gRPC codes → HTTP (NotFound→404, InvalidArgument→400, PermissionDenied→403, Unavailable→503, Internal→generic 500 with server-side log, never a stack trace). Consistent `{"error","detail"}` body | `http/social/errors.go` |
| Pagination | limit/cursor query params, server-side caps | hub/feed handlers |
| Observability | Prometheus registry from runtime-go `metrics.New()`; collectors take a `prometheus.Registerer` (broker pattern); zerolog request-scoped logging | `realtime/broker.go`, middleware |
| User context | Token-decoded uuid in ctx; handlers never trust client-supplied identity | authmw |

**Gaps found:** no Social Foundation routes (feed/global, agents, posts, comments, likes, follow, mute), socialclient missing the Sprint 3 stubs (Agent/Post/Feed), no per-domain BFF metrics, no generic SSE channel (only the derived-stream broker), no transport retry on the gRPC path.

## What this sprint added (same style, no second architecture)

* **Client layer** (`socialclient`): Agent/Post/Feed stubs on the existing bundle; `transport.go` — bounded retry interceptor for IDEMPOTENT reads only (Get/List/Global/Following, Unavailable, 2 retries, backoff) + metadata propagation (`x-insight-user-id`, `x-request-id`); `interfaces.go` — narrow `FeedClient`/`AgentClient`/`PostClient`/`RelationshipClient` slices with compile-time conformance, used by handlers and faked in tests.
* **BFF** (`http/social/foundation.go` + `foundation_dto.go`): 17 routes (Parts 3–10) over the slices; stable snake_case DTOs (PostDTO, FeedItemDTO, AgentDTO, CommentDTO, PostReactionDTO, RelationshipDTO, FeedUpdatesDTO) — additive-only evolution, zero gRPC leakage (asserted by test).
* **SSE foundation** (`http/events/stream.go`): `/v1/events/stream` — authenticated, hello event advertising heartbeat cadence, comment heartbeats, graceful disconnect, NO business events.
* **Metrics** (`http/social/observability.go`): the 7 specified collectors + per-route instrumentation middleware; dashboard `observability/grafana/gateway_social_bff_dashboard.json` (6 panels: rate, p95, errors, feed/post/relationship traffic).

## Security review (Part 14)

| Check | Result |
|---|---|
| Auth propagation | All 17 routes wrapped in `requireAuth`; SSE validates token before the stream opens. Upstream calls annotated with the token user id (observability metadata only) |
| Impersonation | **Impossible by construction**: acting user id is read from `authmw.UserID(ctx)` exclusively; `author_id`/`user_id` in bodies/queries are ignored (regression-tested: `TestActingUserAlwaysComesFromToken`, `TestCreatePostAuthorIsTokenUser`) |
| Ownership | Delete passes `requester_id` = token user; SOCIAL validates author==requester (gateway never decides permissions) |
| Authorization boundaries | Public BFF can only create `author_type=user` posts; agent/admin posts enter Social via the internal Nexus path only |
| Rate limits | Platform-level middleware (BodyLimit + existing OTP cooldowns) unchanged; per-route rate limiting deferred to the edge (documented dependency) |
| Pagination abuse | `limit` clamped to 100 server-side (tested) |
| Oversized payloads | 64KiB JSON body cap on writes (tested) + global `middleware.BodyLimit` |
| Replay safety | All mutations idempotent at Social (likes/follows ON CONFLICT; re-follow `AlreadyExists` treated as success for mobile retries) |
| Error hygiene | 5xx bodies generic; upstream detail logged server-side only (tested) |

## Remaining dependencies

1. Social must run with migration 00005 applied (agents seeded) — the BFF surfaces 404/empty otherwise.
2. Edge rate limiting (per-user request budgets) — infra-level follow-up.
3. `GET /v1/agents/:id/posts` currently serves the agent-authored slice of the caller's global feed page; a dedicated Social `PostsByAuthor` RPC can replace the implementation without changing the route.
4. Business events on `/v1/events/stream` (feed updates push) — next realtime sprint.
