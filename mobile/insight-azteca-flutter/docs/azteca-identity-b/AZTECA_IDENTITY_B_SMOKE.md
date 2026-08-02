# AZTECA-IDENTITY-B — Smoke Test & Classification

## Classification: **PARTIAL**
All code is complete and green: `flutter analyze` (No issues), `go build` + `go test` pass on
insight-social and insight-gateway (0 failures). **Backend changed, so a production deploy IS required**
(Stage 7) before production smoke (Stages 6/8) can pass — and deploy + on-device validation against
Google Cloud cannot be executed from this environment. Steps are ready for the operator.

## Changed services (Stage 6 — build only these)
- **insight-social**: migration `00008_avatar_version.sql` (avatar_updated_at); `userrepo`/`feedrepo`
  versioned avatar; new `httpapi/sports_profile.go` (`GET /users/{id}/sports-profile`); registered.
- **insight-gateway**: `interactions` handler `SportsProfile` proxy; route `GET /v1/users/{userId}/sports-profile`.
- **NOT changed**: insight-anvil (analytics) and all other services — do not rebuild/deploy.

## Flutter (no deploy; ships in the app build)
- `SportsProfileDto` (+ grouped stats) + `sportsProfile()` service + `sportsProfileProvider`.
- Own + public profiles consume the single enriched payload (followers/following/communities/posts/
  signals + role + versioned avatar). Avatar invalidation: backend `?v=` is primary; `evictAvatarFromCache`
  remains the fallback (IDENTITY-A).
- Sports role chip (Stage 4, supporter active; player/coach/scout/analyst/referee/club render-ready).
- Profile completeness card (Stage 3) — deterministic %, missing-item suggestions, owner-only.
- Settings: added LOCAL "Cache → Limpar cache de imagens"; theme/cache = local, prefs = remote.

## Validation status
- [x] `flutter analyze` — No issues.
- [x] `go test ./...` — insight-social 0 fail, insight-gateway 0 fail.
- [~] Flutter widget tests: `social_integration_test` passes; 3 `home_screen_test` cases fail —
      **pre-existing**, unrelated to Identity (they look for `FloatingBottomNav`; the app uses
      `FixedBottomNav` since AZTECA-NAVIGATION-A). Not introduced here.
- [ ] Production deploy of social+gateway to Google Cloud — **pending operator**.
- [ ] On-device production smoke — **pending operator**.

## Stage 7 — deploy (operator, official GCloud only)
1. Run goose migration `00008` on the social DB.
2. Build + push images for **insight-social** and **insight-gateway** only.
3. Deploy those two services to the official Google Cloud environment (never an unofficial compose).

## Stage 8 — production smoke (run against deployed GCloud, with token `$T`)
```
curl -s -H "Authorization: Bearer $T" \
  https://insight-api.konohalabs.com.br/v1/users/<id>/sports-profile | jq .
# expect: {id, username, display_name, reputation, avatar_url:"…?v=…", role:"supporter",
#          stats:{followers,following,communities,posts,signals}, location:null, favorite_team:null}
```
On-device:
1. Avatar upload → upload again (replacement): new image appears on Profile, **Feed**, comments, replies
   with NO restart (URL `?v=` changes).
2. Own profile stats render (followers/following/communities/posts/signals) from the single payload.
3. Profile completeness % reflects filled fields; missing items listed.
4. Role chip shows "Torcedor".
5. Settings: toggle push/email/language → restart → persisted (remote); theme/cache → local only.
6. Public profile (tap another user) loads enriched stats; Follow/Unfollow round-trips.

## To reach READY
Deploy social+gateway to GCloud and pass the Stage 8 checklist. (Optional future backend: model
`location` + `favorite_team` so completeness can reach 100% and those identity fields populate.)
