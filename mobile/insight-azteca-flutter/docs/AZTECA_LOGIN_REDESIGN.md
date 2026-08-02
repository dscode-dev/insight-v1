# Azteca Login & Registration (Azteca-Y Part 1)

## Auth contract (the constraint)

Azteca's backend identity is **phone-OTP** (Gateway): `/v1/auth/otp/request` →
`/v1/auth/otp/verify` → `/v1/auth/register` (`username`, `displayName`,
`accentColor`). There is **no email/password** in the contract. Per the sprint's
"use existing backend contracts / do not create parallel auth flows", we map the
requested fields to the real contract instead of fabricating an email/password
flow.

## Login (`phone_entry_screen.dart`)

Premium WhatsApp-style entry retained + strengthened (Azteca-X): transparent
Insight mark (`BoxFit.contain`, no black square), strong wordmark, and the
positioning line **"Sports Intelligence Platform"** so the screen communicates
the product, not a generic form. Country tile + live BR phone formatting +
bottom-anchored CTA (clear of the keyboard) + OTP loading/error states.

## Registration (`username_screen.dart`) — enhanced this sprint

The post-verify profile step now collects **Nome + Sobrenome + Username**:
- `Nome` (givenName) + `Sobrenome` (familyName) compose the real `displayName`
  (`[first, last].join(' ')`), submitted to `/v1/auth/register`.
- `@username` (3–32, `[a-z0-9._-]`) with live filtering + local validation.
- Loading spinner + inline field errors + server error banner.

**Intentionally NOT added: email + password** — they aren't part of the
phone-OTP identity contract; adding them would be a parallel/fake auth flow,
which the sprint forbids. Registration "exists" and is integrated with the real
endpoint (criterion #2).

## Identity

The flow stays **Insight** (sports intelligence) — onboarding copy
"Inteligência social esportiva… sem palpites, sem 'dicas'", not a generic social
sign-up. `flutter analyze` clean.
