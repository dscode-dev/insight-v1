# AZTECA-POSTS-B — Media Attachment Architecture (design; NOT implemented this sprint)

## Decision
Media/attachment persistence is **designed but NOT implemented** this sprint, because GIF (the only V1 media
driver) is DEFERRED_OPERATIONAL (see GIF_DECISION). Adding an attachment schema/DTO change for a deferred,
unprovisioned feature is neither justified nor low-risk (Stage 7 gate). Text-only posts remain 100% intact.

## Approved additive design (for the sprint that provisions GIF)
Represent attachments **additively via post `metadata`** first (no migration), promotable to a first-class
column later:
```
metadata: {
  "attachment": {
    "type": "gif",
    "provider": "<allowlisted>",
    "external_id": "...",
    "preview_url": "https://<allowlisted-cdn>/...",
    "media_url":   "https://<allowlisted-cdn>/...",
    "width": 480, "height": 270,
    "alt_text": "..."
  }
}
```
Rules (server-enforced when implemented):
- text-only posts stay valid; existing rows unchanged; DTO is backward compatible (attachment optional).
- provider + CDN host **allowlisted**; bounded metadata size; bounded attachment count (1 for V1 GIF).
- **external reference only** — Insight stores the provider media/preview URL + id; it does NOT download/
  re-upload GIF bytes into Insight object storage (so avatar-storage absence does not block GIF).
- no arbitrary remote HTML/executable; no client-selected proxy destination; safe serialization.

## Trust model
The client never persists provider raw blobs. The GIF media/preview URLs are provider-CDN references
validated against an allowlist at create time. Attachment is inert display data (image frames), rendered by
a dedicated renderer (see below), never executed.

## Renderer (design)
Evolve `feed_item_renderer.dart` into compositional dispatch: `TextContentRenderer` +
`GifAttachmentRenderer` (stable aspect ratio, placeholder, load-failure state, reduced-motion, semantic
label, no color-only state). Reused across Feed/Activity/Detail. Not built until GIF is approved.
