# AZTECA-POSTS-B — Idempotency & Retry

## Classification
| Operation | Class | Notes |
|---|---|---|
| Create post | **NON_IDEMPOTENT** | `POST /v1/posts` inserts a new row per call; no idempotency key. Retry-after-timeout CAN duplicate. |
| Create comment/reply | **NON_IDEMPOTENT** | same shape. |
| Like / Unlike | **IDEMPOTENT_BY_CONSTRAINT** | `post_likes` PK (post_id,user_id); re-like is a DB no-op. |
| Save / Unsave | **IDEMPOTENT_BY_CONSTRAINT** | `saved_posts` unique (user_id,post_id) ON CONFLICT DO NOTHING. |
| Boost / Unboost | **IDEMPOTENT_BY_CONSTRAINT** | manual-boost uniqueness per (post,user). |

## Create-post duplicate risk — current mitigation (client) + recommendation (backend)
- **Client (in place):** the composer's `if (publishing.value) return` prevents double-tap; the dio
  `_RetryInterceptor` retries **GET only** (mutations are never auto-retried). So the common duplicate
  vectors (double-tap, transport auto-retry) are already closed. A manual user retry after a TRUE timeout
  (request sent, response lost) remains a theoretical duplicate window.
- **Recommendation (NOT implemented — needs backend, out of this sprint's safe scope):** additive
  idempotency — client sends `Idempotency-Key` (uuid v4) on `POST /v1/posts`; Social stores a short-TTL
  unique (author_id, idempotency_key) and returns the original post on a safe retry. This achieves
  **at-least-once request delivery + idempotent command handling** (NOT exactly-once). Deferred because it
  requires a Social migration + gateway header plumbing and the current client mitigations make the
  residual risk low for V1.

## Statement of what is actually achieved today
Duplicate-submit (UI) prevented; transport auto-retry of mutations disabled; post-create is at-least-once at
the true-timeout boundary with no server dedupe yet. No exactly-once is claimed.
