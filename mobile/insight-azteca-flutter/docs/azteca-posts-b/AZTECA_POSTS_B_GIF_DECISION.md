# AZTECA-POSTS-B — GIF Delivery Decision

## DECISION: **DEFERRED_OPERATIONAL**

## Evidence
1. **No provider is provisioned.** No `/v1/gifs/*` routes and no `TENOR_*`/`GIPHY_*` env/config exist in
   insight-gateway (grep clean). The architecture MANDATES the provider API key live server-side only
   (never in Flutter) — obtaining a provider account + key + accepting provider Terms/attribution is an
   operational decision the agent cannot and must not make/fabricate.
2. **Media infrastructure is immature.** Avatar object storage is still unprovisioned (QUALITY-A:
   OBJECT_STORAGE_CONFIGURATION_FAILURE). While GIF-by-external-reference avoids Insight object storage, the
   absence signals the media platform is not yet operationalized.
3. **Scope/risk.** Implementing GifProvider BFF + picker + compositional renderer + additive media contract
   without an approved+provisioned provider would be speculative and risks violating "do not fabricate
   provider functionality" and "do not couple permanently to one vendor" without real validation.

## Why not the other deferral classes
- Not DEFERRED_CONTRACTUAL: no specific licensing blocker was hit (we didn't get far enough — provider not chosen/provisioned).
- Not DEFERRED_ARCHITECTURAL: the architecture is sound (BFF + vendor-neutral `GifProvider` + external-ref
  metadata, documented in MEDIA_ARCHITECTURE) — the blocker is operational provisioning, not design.

## Provider recommendation (for the enabling sprint — not adopted now)
**Tenor (Google)** or **GIPHY**, integrated ONLY via a Gateway BFF (`GET /v1/gifs/search`, `/v1/gifs/trending`)
that injects the key server-side, normalizes to a vendor-neutral DTO, caps response size, validates query
length, propagates correlation id, respects attribution, and never logs the key. No `?url=` proxy; no
client-chosen host. A small custom Flutter picker over that BFF is preferred over any package that would
embed credentials or bypass the Gateway.

## V1 consequence
GIF is **not** in this V1 closure. Text-only posting is fully complete and backward compatible. The media
foundation is designed (MEDIA_ARCHITECTURE) so the enabling sprint is small once a provider is provisioned.
This does NOT make the sprint PARTIAL — GIF was explicitly optional under the Stage 0 decision gate and the
mandatory publishing lifecycle is READY.
