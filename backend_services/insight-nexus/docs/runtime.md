# Nexus runtime

Nexus reads configuration from process environment variables. The canonical
Robozão Compose passes these into the `nexus` container. Provider credentials
belong in the deployment secret environment, never in source control. Copy
`.env.example` only as a key-name template.

## Identity

The admin API is guarded by the **Insight Control Plane**, per
`insight-context.md` v2.0 — every administrative operation goes through it,
and the Gateway is explicitly not responsible for operators.

| Variable | Effect |
|---|---|
| `NEXUS_CONTROL_PLANE_TOKEN` | Shared secret. Set ⇒ admin API unlocked, Gateway never contacted |
| `NEXUS_GATEWAY_IDENTITY_URL` | **Legacy** fallback, used only when the token above is empty |
| *(neither set)* | Admin API answers **503**, naming the variable that unlocks it |

The Control Plane forwards the operator on headers: `X-Control-Plane-Token`,
`X-Operator-Id`, `X-Operator`, `X-Operator-Role`, `X-Operator-Permissions`.

Nexus does not resolve role → permission. It declares what its own routes
*require*; the Control Plane declares what the operator *holds*. A request
arriving without `X-Operator-Permissions` is **denied**, not defaulted — a
forgotten header must not grant everything.

## Publication

Two independent switches, plus credentials:

1. `NEXUS_ENABLE_ANTHROPIC` / `_OPENAI` / `_GEMINI` register an adapter.
2. The API key makes it usable (empty key = registered and offline).
3. `NEXUS_PUBLISHER_ENABLED` starts the publish worker.

This lets drafts be generated and inspected with nothing reaching Social.

`OPENAI_MODEL`, `ANTHROPIC_MODEL` and `GEMINI_MODEL` are canonical; the older
`NEXUS_*_MODEL` names remain fallback aliases.

### Boot refuses two misconfigurations

- **Publisher on, no provider enabled.** Every draft would reach
  `ErrAllProvidersFailed` and open a ticket. A slow flood of tickets is
  harder to read than one boot error.
- **Publisher on, no `NEXUS_SOCIAL_GRPC_ADDR`.** There is nowhere to publish.

> The variable is `NEXUS_SOCIAL_GRPC_ADDR`, with the prefix. The Compose file
> passed `SOCIAL_GRPC_ADDR` for a while, so the address never reached the
> service — invisible while the publisher was off.

## The two loops

```
trend consumer → pipeline → per-agent publishing queue     (fast)
publish worker ← queue    → LLM → validate → Social        (slow)
```

They are separate processes-within-the-process on purpose. Publication takes
up to one LLM timeout **per provider**; running it inside the trend consumer
stalled every other agent and every later trend, and the queues were written
but never read.

| Variable | Meaning |
|---|---|
| `NEXUS_PUBLISH_CONSUMER_GROUP` | Queue consumer group (separate from the trend group) |
| `NEXUS_PUBLISH_CONSUMER_NAME` | This instance's name within it |
| `NEXUS_QUEUE_MAX_LEN` | Advisory. It no longer trims — see below |

The queue is **not** capped. `MaxLen` with `Approx` trims the *oldest*
entries, and the oldest entry on a publishing queue is the draft that has
waited longest to be published. Capping deleted exactly the most overdue
work, silently. Backlog is something to alarm on (`nexus_queue_depth`), not
something to hide.

## Pending recovery

`NEXUS_CLAIMER_MIN_IDLE` is how long a pending entry must sit before another
consumer may claim it. If that is shorter than the handler's worst case, a
second replica reclaims a trend that is still in flight — and both publish.

Left unset **it is derived**: `NEXUS_LLM_TIMEOUT × provider count`. Set
explicitly below that floor, the service refuses to boot rather than
silently correct a number someone chose.

Deriving rather than hardcoding matters because raising `NEXUS_LLM_TIMEOUT`
would otherwise invalidate a hand-picked MinIdle without any signal.

## Removed

`OLLAMA_BASE_URL`, `NEXUS_QWEN_MODEL` and `NEXUS_LLAMA_MODEL` were required
by Compose and read by nothing — leftovers from local models, which the
private-provider policy removed. They blocked deploys without affecting
behaviour.
