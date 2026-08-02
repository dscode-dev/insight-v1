# AZTECA-PROFILE-B — Profile Completeness

## Defect fixed (Stage 14)
IDENTITY-B's completeness checklist included `Time favorito` (favoriteTeam) and `Localização` (location) in the
denominator. These are **unmodeled + not user-actionable in V1**, so the user was permanently penalized —
100% was impossible. Violates "completeness must only consider real, available, user-actionable fields."

## Fix (`profile_completeness.dart`)
Removed favoriteTeam + location from the checklist. Remaining items are all achievable through actions the
user can take now:
- Foto de perfil (avatar — Edit Profile / picker);
- Nome de exibição (display name — Edit Profile, now writable);
- Nome de usuário (set at signup);
- Comunidades (join one).
⇒ 100% is now attainable.

## Guarantees (unchanged)
Deterministic (done/total), no AI, no fake suggestions, owner-only (never shown on public profiles — no
completeness leakage), percentage is simple `completed/total`. When the backend models bio/team/location and
Edit Profile exposes them, they can return to the denominator.
