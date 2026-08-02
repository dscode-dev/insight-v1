# AZTECA-QUALITY-A — IDENTITY-B Live Contract Validation

## Deployed state (evidence)
| Check | Result | Evidence |
|---|---|---|
| `GET /v1/users/{id}/sports-profile` registered | **YES** | Live: unauth → **401** (auth-gated, exists); gateway main.go:609 registers it |
| Gateway version | 0.1.13 | `docker inspect insight-gateway` |
| Social version | 0.1.8 | `docker inspect insight-social` |
| IDENTITY-B migration (`avatar_updated_at`) applied | **YES** | read-only `psql`: `users` has `avatar_url` + `avatar_updated_at` |
| Feed/interaction endpoints registered | YES | `/v1/feed/global` → 401 |

## Field-level payload (followers/following/communities/posts/signals, role, versioned avatar)
Requires an AUTHENTICATED session with a safe test account. No such credentials were available to the agent,
and per the deployment policy no production user was created and no mutation performed. Documented manual
smoke below — NOT fabricated.

### Manual smoke (user-operated; read-only except the optional avatar step)
```
# 1. Obtain an access token via the normal phone+OTP login for a TEST account.
TOK=<access_token>
B=https://insight-api.konohalabs.com.br
# 2. Owner sports-profile — expect 200 + grouped stats + role + (versioned) avatar_url.
curl -s "$B/v1/users/$MY_ID/sports-profile" -H "Authorization: Bearer $TOK" | jq
#    Verify: stats.followers, .following, .communities, .posts, .signals present; role present;
#    unsupported nullable fields honest (null, not fabricated); no owner-only controls in payload.
# 3. Public profile of ANOTHER user — expect 200, same shape, no owner-only fields.
curl -s "$B/v1/users/$OTHER_ID/sports-profile" -H "Authorization: Bearer $TOK" | jq
# 4. follow/unfollow still real:
curl -s -XPOST "$B/v1/follow/$OTHER_ID" -H "Authorization: Bearer $TOK" -o /dev/null -w '%{http_code}\n'
```

## Versioned-avatar-after-update: BLOCKED_BY_ENVIRONMENT
The `?v=<avatar_updated_at>` bump can only be exercised by performing an avatar upload, which is currently
impossible (no MinIO — see AVATAR_TRACE). Once object storage is provisioned + the Gateway 503-fix deployed,
re-run: upload avatar → GET sports-profile → confirm `avatar_url` contains a new `?v=` token.

## Verdict
IDENTITY-B read contract is **DEPLOYED and live** (endpoint 401, migration applied). Field-level +
versioned-avatar validation is **PARTIALLY_VALIDATED_LIVE** (contract reachable; authenticated payload +
avatar-version pending a safe test session / MinIO).
