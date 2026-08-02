# AZTECA-QUALITY-A — Legal / Store-Facing Organization Changes

Organization for legal/store-facing identity = **AllBlue-Labs**. Surgical changes only; infrastructure
references preserved. Material ownership change ⇒ Terms + Privacy versions bumped (re-triggers EULA
acceptance, which records `accepted_terms_version` at register) + effective date refreshed.

## Before → After (user-facing legal ownership)
| File:line | Before | After |
|---|---|---|
| `lib/core/legal.dart` (Terms §12 liability) | "o Insight e a **KonohaLabs** não respondem…" | "o Insight e a **AllBlue-Labs** não respondem…" |
| `lib/core/legal.dart` (Privacy §1 controller) | "A **KonohaLabs** é a controladora dos dados…" | "A **AllBlue-Labs** é a controladora dos dados…" |
| `lib/features/profile/settings_screen.dart:255` (About) | "**KonohaLabs** · 2026" | "**AllBlue-Labs** · 2026" |
| `lib/core/legal.dart` kTermsVersion | `1.1` | `1.2` |
| `lib/core/legal.dart` kPrivacyVersion | `1.1` | `1.2` |
| `lib/core/legal.dart` kLegalEffectiveDate | `16/06/2026` | `04/07/2026` |

## Deliberately NOT changed (documented decision)
- **Support/moderation emails** (`suporte@konohalabs.com.br`, `moderacao@konohalabs.com.br`): the legal OWNER
  is AllBlue-Labs, but the mailbox DOMAIN is infrastructure. An invented AllBlue-Labs address would route
  users to a non-existent inbox (worse than a working one). **Decision required from the org:** confirm the
  real support domain, then switch. A code comment in `legal.dart` flags this. Not fabricated.
- **Infrastructure (preserved):** `env.dart` Gateway host `insight-api.konohalabs.com.br`;
  `startup_diagnostics.dart` host assertion; `routes.dart` universal-link domain. These are technical, not
  legal identity — a blind swap would break the app / deep links.
- **`sponsored_provider.dart` mock "Konoha Labs":** demo/placeholder sponsored content, not legal ownership.
  Remove/replace with a real sponsor before store — tracked, not a legal correction.

## Test
`test/legal_org_test.dart` — asserts controller+liability read AllBlue-Labs (not KonohaLabs) and versions=1.2.

## Store metadata
Confirm the App Store / Play **publisher** shows AllBlue-Labs (android/ios store listing config) — a manual
store-console step outside the repo; flagged in DEPLOY.
