# Azteca Environment Strategy (Azteca-X Part 7)

## Environments

| env | base URL | use |
|---|---|---|
| `dev` | `http://localhost:8080` | simulator against a gateway on the dev machine |
| **`local`** | **`http://136.115.122.177:8080`** | **physical device on the lab LAN → SanninJiraiya Gateway** |
| `staging` | `https://insight.konohalabs.com.br/<region>` | public edge (staging) |
| `production` | `https://insight.konohalabs.com.br/<region>` | public edge (production) |

`region` defaults to `cloud` (the public app prefix); `big-robot` exists for the
internal station and is never used by the app. `LOCAL_API_BASE_URL` and
`API_BASE_URL` dart-defines override for other LANs/tunnels.

## How switching works

- **Build-time** (`lib/core/env.dart`): `--dart-define=ENVIRONMENT=local|staging|production`.
- **Runtime** (`lib/core/environment_store.dart`, Azteca-X): dev/staging builds
  persist an environment override (flutter_secure_storage), applied at startup
  (`main()` → `EnvironmentStore.restore()`) BEFORE the first request. A
  **Settings → Ambiente** switcher lets an operator pick local/staging/
  production and invalidates `gatewayDioProvider` so the next request uses the
  new base URL. A **production build ignores the override** (`InsightEnv.
  environment` guards it) — production is locked to its public Gateway.

```bash
# run pointing at the local lab gateway
flutter run --dart-define=ENVIRONMENT=local
# or override the host explicitly
flutter run --dart-define=ENVIRONMENT=local --dart-define=LOCAL_API_BASE_URL=http://192.168.1.61:8080
```

## Public entrypoint decision

**Azteca consumes the Gateway ONLY — never Social (or any internal service)
directly.** Social is internal-only (gRPC, no public port); the Gateway is the
social BFF + auth + uploads. Therefore:

- The correct public entrypoint is the **Gateway** at
  `https://insight.konohalabs.com.br/<cloud>` with `/v1/...` in the path
  (e.g. `…/cloud/v1/auth/otp/request`, `…/cloud/v1/feed`).
- The sprint's `/social/v1` option is **rejected** — exposing Social publicly
  would bypass the Gateway's auth/BFF/rate-limit boundary. `…/gateway/v1` and
  `…/cloud/v1` are equivalent intents; the deployed edge prefix is `cloud`.
- **Production never consumes internal services directly** — enforced in code:
  `local` (136.115.122.177) is unreachable from a production build, and the
  runtime override is disabled in production builds.
