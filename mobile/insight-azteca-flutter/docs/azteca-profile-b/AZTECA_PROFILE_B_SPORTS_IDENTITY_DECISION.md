# AZTECA-PROFILE-B — Sports Identity Ownership Decision

Derived from the real schema (never from UI placeholders).

## Classification
| Attribute | Class | Rationale |
|---|---|---|
| display_name | CORE_IDENTITY (editable) | `users.display_name` — the one writable identity text field |
| username | CORE_IDENTITY (not editable V1) | unique + deep-link key; changing it is unsafe without confusable/reserved policy + migration evidence |
| avatar | CORE_IDENTITY (editable via upload) | dedicated storage path |
| accent_color | CORE_IDENTITY (deferred) | modeled + has gRPC UpdateAccent, but needs a color-picker UX; deferred, not fabricated |
| role | SPORTS_IDENTITY (deferred) | NOT persisted per-user; backend returns const "supporter". No fake editor. |
| favorite_team | SPORTS_IDENTITY (deferred) | unmodeled; requires a canonical team relation — a free-text string would conflict with team identity |
| location | CORE/ SPORTS (deferred) | unmodeled; if introduced, city/region granularity only (no coordinates) |
| reputation, level, tier | DERIVED_METRIC | server-computed; never editable |
| followers/following/communities/posts/signals | RELATIONSHIP_PROJECTION | counts; never editable |
| theme, language pref | DEVICE/REMOTE PREFERENCE | Settings, not identity |

## Role
Backend does not persist a per-user role (always "supporter"). Decision: **keep rendering the authoritative
role; do NOT expose a role editor** (would let Flutter send arbitrary role strings). Future contract: a
`user_roles` model + backend-authoritative option list before any editor ships.

## Favorite team
No canonical user↔team relation exists. Decision: **defer** — do not add a weak free-text field that later
conflicts with team identity. Model a proper relation (reuse the competitions/team domain) when justified.

## Location
Unmodeled. Decision: **defer** — if added, optional city/region/country strings with public visibility, never
coordinates/precise geolocation.

## V1 Sports Identity outcome
V1 Sports Identity = authoritative-rendered (role/reputation/level/counts) + ONE editable Core Identity field
(display_name) + avatar. Everything else is honestly deferred (shown disabled/"Em breve", never fake-enabled).
