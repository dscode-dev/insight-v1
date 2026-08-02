# AZTECA-PROFILE-B — Edit Profile UX

## Decision: dedicated route `/profile/edit` (not a bottom sheet)
Justified by multiple concerns (text field + avatar action + keyboard + honest deferred section). The Edit
button (`OwnerProfileActions.onEdit`) now `context.push(R.editProfile)` — was `_pickAndUpload` (avatar picker).
The header avatar tap remains a quick shortcut.

## `EditProfileScreen` behavior (real)
- **Hydrates** the authoritative display name from `authProvider` on init.
- **Only real editable field is an input**: one `TextField` (display name). Username is read-only (context).
  Bio / Time favorito / Localização are shown as **explicitly deferred "Em breve" rows (disabled, Semantics
  enabled:false)** — NOT fake-enabled inputs.
- **Dirty state**: Save is enabled only when the name changed AND is valid (non-empty, ≤64 runes).
- **Duplicate submit prevented** (`if (_saving) return`).
- **Values preserved on failure** (form stays; inline error).
- **Save only after authoritative backend confirmation** (`PATCH /v1/users/me` resolves) → then reconcile +
  `context.pop(true)`. No optimistic pop.
- **Local + backend validation**: local for instant UX; backend is authoritative (maps
  `display_name_too_long`/`required`/409/401/timeout/network to honest messages).
- **Avatar in-form**: "Alterar foto" runs the picker+upload; a failure/unavailability (503) shows an honest
  message and **never discards the in-progress text edits** (separate `_avatarBusy`/`_avatarError` state).

## Tests (`test/edit_profile_test.dart`, 3)
opens a real hydrated form (not the picker); exactly ONE editable TextField (deferred fields are not inputs);
Save is dirty-gated (disabled until changed, disabled again when blank).
