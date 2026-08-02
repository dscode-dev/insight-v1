# AZTECA V1 — Legal & Organization Audit (Stage 10)

Required: user-facing legal / store-facing identity = **AllBlue-Labs**. Do NOT blindly replace internal/
infrastructure references. Distinguish categories below.

## MUST CHANGE — user-facing legal ownership & store attribution (→ AllBlue-Labs)
| File:line | Current | Category |
|---|---|---|
| `lib/core/legal.dart:99` | "o Insight e a **KonohaLabs** não respondem por perdas…" | Terms — liability owner |
| `lib/core/legal.dart:122` | "A **KonohaLabs** é a controladora dos dados tratados pelo Insight…" | Privacy — data controller |
| `lib/features/profile/settings_screen.dart:255` | About subtitle "**KonohaLabs** · 2026" | Copyright/About attribution |
| `lib/core/legal.dart:16-17` | `suporte@konohalabs.com.br`, `moderacao@konohalabs.com.br` | Support/moderation contact (user-facing) — decide AllBlue-Labs contact domain |
| App store org metadata | AllBlue-Labs (verify android/ios store listing config) | Store-facing publisher |

Also re-audit the full bundled legal document bodies in `legal.dart` for any other "Konoha"/"Konoha Labs"
mentions in Terms/Privacy/UGC section text before store submission.

## REVIEW — demo/mock content (user-facing but placeholder)
| File:line | Current | Note |
|---|---|---|
| `lib/providers/sponsored_provider.dart:54-71` | mock sponsor "Konoha Labs" (`sponsor_konohalabs`, blog.konohalabs.com) | This is demo/mock sponsored content. It is user-facing but a placeholder; remove or replace with real sponsor before store, and it is NOT the legal owner. |

## DO NOT CHANGE — internal / infrastructure (not legal identity)
| File:line | Current | Why keep |
|---|---|---|
| `lib/core/env.dart:66,92,94` | `insight-api.konohalabs.com.br` | Gateway host (infrastructure). Changing it breaks the app. |
| `lib/core/startup_diagnostics.dart:88-93` | host assertion for the cloud gateway | Infra guard. |
| `lib/routing/routes.dart:5` | universal link `insight.konohalabs.com` | Deep-link domain (infra); coordinate with store/domain team separately, not a blind swap. |

## Versioning
`kTermsVersion=1.1`, `kPrivacyVersion=1.1`, `kUgcPolicyVersion=1.0`, effective 16/06/2026. Any legal-text
change (org name) MUST bump the version + effective date, and re-trigger EULA acceptance (register flow
records accepted_terms_version — Store-A).

## Verdict
Legal correction is small, surgical, and store-blocking: ~4 user-facing surfaces in `legal.dart` +
`settings_screen.dart` must read **AllBlue-Labs** (with version bump + re-acceptance). Infrastructure hosts
stay KonohaLabs. This belongs in AZTECA-QUALITY-A (or a dedicated AZTECA-LEGAL-A) and is a hard gate for
store submission.
