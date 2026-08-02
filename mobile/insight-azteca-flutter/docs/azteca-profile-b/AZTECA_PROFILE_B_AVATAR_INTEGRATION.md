# AZTECA-PROFILE-B — Avatar Inside Edit Profile

## Integration (decoupled from the form transaction)
Avatar is one action within Edit Profile, with its own state (`_avatarBusy`, `_avatarError`) separate from the
display-name save. Consequences:
- text profile editing remains fully functional even if avatar storage is unavailable;
- an avatar failure NEVER discards unsaved text edits;
- the display-name Save transaction does not depend on object storage.

## Honest capability handling (QUALITY-A alignment)
The gateway avatar route (0.1.14) always registers and returns **503 CAPABILITY_UNAVAILABLE** when object
storage is unavailable (live env has no MinIO). Edit Profile surfaces this via `avatarUploadErrorMessage`
(top-level, tested): "Envio de foto indisponível no momento." — distinct from invalid-image/timeout/auth.
No pretend success; no local avatar persistence.

## Reconciliation on avatar success
`evictAvatarFromCache(old)` + `evictAvatarFromCache(new)` (cache fallback preserved) →
`authProvider.updateAvatar` → invalidate `sportsProfileProvider(myId)` + `profileBundleProvider` +
`feedProvider`. Versioned avatar URL behavior (IDENTITY-B `?v=`) preserved (server-stamped).

## Blocked-by-environment note
Actual avatar upload success remains BLOCKED_BY_ENVIRONMENT until MinIO is provisioned (QUALITY-A infra
follow-up). The Edit Profile avatar path is correct + honest; it cannot be end-to-end validated live yet.
