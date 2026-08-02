# Azteca Y.5 — Login Polish (Part 1)

## Net change this sprint

The login **experience** now opens on the new **Auth Entry screen**
(`AUTH_PREPARATION`): a premium, balanced first touch — centered Insight brand
block, clear product positioning ("Sports Intelligence Platform"), a single
confident primary action ("Continuar com telefone"), and an expectation-setting
note on why phone is used. This is a stronger, more premium login entry than
dropping the user straight onto a phone-number form, while reusing the existing
`phone_entry_screen` (transparent mark + tagline + live BR formatting + bottom
CTA) unchanged for the actual entry step.

## Hierarchy / spacing / balance

- Entry screen uses `InsightSpacing` tokens + `Spacer` flex ratios (3/2/3) for
  vertical balance on phones → tablets (responsive).
- Brand → primary action → rationale → future-auth: a clear top-to-bottom
  hierarchy (WhatsApp/Linear/Cloudflare-inspired, not copied).

## Preserved

Routes, providers, the phone-OTP contract, and the existing phone/OTP screens.
No full-screen redesign — the flow is evolved with a premium landing.
`flutter analyze` clean.
