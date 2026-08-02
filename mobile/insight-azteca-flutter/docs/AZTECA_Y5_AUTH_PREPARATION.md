# Azteca Y.5 — Authentication Preparation (Part 2)

UI/UX preparation for the future Auth-A sprint. **No Firebase, no WebAuthn, no
backend** — visual + flow scaffolding only. Routes/providers/contracts preserved.

## Auth Entry Screen (new)

`lib/features/auth/screens/auth_entry_screen.dart` + route `R.authEntry`
(`/auth/entry`). It is now the **auth landing** (router redirect sends
anonymous, onboarded users here instead of straight to phone). Contents:
- Insight brand block (transparent mark + "Sports Intelligence Platform").
- Primary **"Continuar com telefone"** → `context.go(R.authPhone)` (the existing
  phone-OTP flow — unchanged).
- Expectation-setting line: *"A verificação por telefone é usada apenas na
  criação da conta e na recuperação de acesso."*
- A disabled **"Face ID · Touch ID · Passkey — Em breve"** card (future-auth
  affordance, visual only).

Routing change is additive: `R.authPhone/authOtp/authUsername` are untouched;
`login`/`register` aliases now point at `authEntry`. The redirect's two auth
landings (`onSplash` + `anonymous`) point at `authEntry`.

## Future Passkey UI state

Persistent **Settings → Segurança** section: a disabled "Login biométrico —
Face ID · Touch ID · Passkey — em breve" tile. This is the UI slot Auth-A will
activate (Face ID / Touch ID / Android Biometrics / Passkeys). No logic, no
plugin, no secrets.

## Guarantees

- No `firebase_*` / WebAuthn dependency added.
- Phone-OTP remains the only active method; `/v1/auth/*` contracts unchanged.
- Pre-existing untracked `google-services.json` / `GoogleService-Info.plist`
  were **not** committed or wired (Firebase stays out of scope).
