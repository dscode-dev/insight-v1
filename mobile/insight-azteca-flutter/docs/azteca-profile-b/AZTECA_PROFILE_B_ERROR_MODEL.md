# AZTECA-PROFILE-B — Error & Conflict Model

## Profile edit (display name) — distinct, honest causes
`EditProfileScreen._humanizeProfileError` maps:
| Cause | Backend signal | Message |
|---|---|---|
| Invalid (too long) | 400 `display_name_too_long` | "Nome muito longo (máx. 64)." |
| Invalid (empty) | 400 `display_name_required` | "Digite um nome de exibição." |
| Conflict (future username) | 409 / taken / conflict | "Esse nome já está em uso. Tente outro." |
| Auth expired | 401 unauthorized | "Sua sessão expirou. Entre novamente." |
| Timeout | timeout | "Tempo esgotado. Tente de novo." |
| Network | connection/network | "Verifique sua conexão e tente novamente." |
| Generic | other | "Não foi possível salvar agora. Tente novamente." |

## Avatar (in Edit Profile) — distinct causes (QUALITY-A `avatarUploadErrorMessage`)
invalid-image (415), too-large (413), **service-unavailable (503 CAPABILITY_UNAVAILABLE)**, auth (401),
timeout, network — each distinct. Avatar failure preserves text edits.

## No leakage
No hostnames / DB / MinIO / bucket / stack traces / tokens in any message. Backend errors are short codes
(`display_name_too_long`, `profile_update_failed`, `avatar_storage_unavailable`).

## Form-data preservation
On any recoverable failure the form keeps the user's input (`_saving=false`, values intact) and offers retry.
