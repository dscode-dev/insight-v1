# AZTECA V1 — GIF Support Architecture (Stage 8)

## Current reality (CONFIRMED)
- **Post model is text-only**: `models/social.dart` / `models/feed.dart` have NO media/attachment/gif/
  mediaUrl/mediaType fields (grep returned nothing). Backend posts: `content` (text) + `metadata` (JSONB) +
  `visibility`; no media column.
- **Media upload route is gated OFF**: `post_uploads` flag OFF → `/v1/feed/uploads` does not exist
  (`env.dart` flagPostUploads). `post_upload_service.dart` exists but is gated.
- FeedRenderers architecture (FEED-A): renderer registry; currently only `TextPostRenderer`. Prepared for
  future renderers.
⇒ GIF requires: a media representation on the post domain + a rendering renderer + a GIF source provider.
Nothing exists today; this is an architecture proposal, NOT an implementation.

## Representation decision
Represent GIF as a **typed attachment via post `metadata`**, not by abusing an image field:
`metadata: { attachment_kind: "gif", gif_url, gif_preview_url, gif_width, gif_height, gif_provider, gif_id }`.
This is additive (metadata is already a free JSONB the composer writes) and avoids a schema migration for V1
IF the feed read returns metadata (verify). If a first-class column is preferred, that is a Social migration
(POST-audit backend sprint). **Recommendation: metadata-based attachment for V1** (no migration, forward-compatible).

## Renderer decision
Add a **dedicated `GifPostRenderer`** (or a `MediaPostRenderer` that handles gif|image) in the FeedRenderers
registry — do NOT bolt GIF onto `TextPostRenderer`. A GIF post is text + one GIF attachment; the renderer
shows the text card + an aspect-ratio-boxed GIF with reduced-motion + tap-to-play.

## Provider abstraction (vendor-neutral)
```
abstract class GifProvider {
  Future<GifPage> search(String query, {String? cursor});
  Future<GifPage> trending({String? cursor});
  Future<List<GifCategory>> categories();
  Future<GifItem> resolve(String id);
}
```
Do NOT hardwire a vendor DTO into the app. Map vendor payload → neutral `GifItem{id, url, previewUrl, width,
height, attribution}` in the provider impl.

## Vendor + transport recommendation
- **Provider: Tenor (Google) or GIPHY.** Tenor has an official API, strong trending/search, Flutter-friendly
  REST, and attribution requirements. GIPHY similar. Both require an API key and attribution branding.
- **Transport: Flutter → Gateway/BFF → provider (NOT Flutter → provider directly).** Rationale: the API key
  must not ship in the client (threat model + provider terms); quota/rate-limit control; content moderation/
  allowlisting; and URL proxying/caching. Add `GET /v1/gifs/search|trending|categories` BFF routes that
  inject the key server-side. This is a BACKEND prerequisite for GIF-in-V1.
- Remote GIF URLs in posts: allowlist provider CDN hosts; persist provider+id for attribution + moderation.

## Playback / performance / a11y
Autoplay muted with `reduced-motion` → show a static preview + play affordance when reduce-motion is on;
cache decoded frames; cap in-feed concurrent playback; bandwidth-aware (preview first). Moderation: GIF posts
flow through the same content moderation as text (author-hidden/ViewFor already applies at post level).

## Verdict / V1 call
GIF-in-V1 is feasible but has a **backend prerequisite** (GIF BFF proxy + metadata attachment surfaced in
feed reads). Classify **V1_OPTIONAL_IF_LOW_RISK**: include only if the GIF BFF proxy lands; otherwise POST-V1.
Client work (provider abstraction + GifPostRenderer + composer picker) is well-scoped once the proxy exists.
