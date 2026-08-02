# AZTECA-PROFILE-B — Signals

## Audit
A `signals` table exists in Social (the sports-profile handler counts `SELECT COUNT(*) FROM signals s WHERE
s.author_id = u.id` as `signals`). So a signals COUNT is real and surfaced in Statistics. However:
- there is **no dedicated Signals tab** in the profile (tabs are Atividades / Comunidades / Estatísticas);
- there is **no read endpoint** returning a user's signal LIST (only the count);
- signal semantics (user-authored vs Atlas-generated vs derived) are not exposed via a V1 client contract.

## Decision: honest — surface the real COUNT only; no fabricated signal cards
The signals count is shown in Statistics (real). A signals feed/list surface is NOT built (no list endpoint;
building one risks straying into Atlas feature work — Atlas 1.0.0 is frozen). No signal cards are fabricated.

## Status: PARTIAL (honest)
Real signal COUNT surfaced; no fabricated list. A future signals read surface (list endpoint + tab) is a
separate, evidence-gated effort, not part of this Profile closure.
