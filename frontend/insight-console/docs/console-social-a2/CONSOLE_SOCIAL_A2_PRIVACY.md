# CONSOLE-SOCIAL-A2 — Privacy Guarantees

## Save privacy: AGGREGATE ONLY (backend-enforced, not UI-hiding)
- The Social read plane exposes only `save_count` (aggregate) on post projections. There is **no
  endpoint, adapter method, or read model** that returns individual saver identities (no `saved_posts.
  user_id` list). The `/console/social/*` surface has no `savers`/`saved-by` route.
- Console `SocialControlPlane` has **no** saver-listing method (regression test asserts no method
  matching /saver|savedby|savelist|whosaved/).
- Therefore a browser can never receive saver ids/usernames/profiles — the guarantee lives in the
  contract, not the UI.

## No fabricated user↔agent ownership
Agents have no owner in Social. No `owner`/`owner_user_id`/`linked_user_id` is returned or rendered;
agent investigation shows identity type "Platform agent". user→agent follow is a follow relationship
only — never ownership/linkage.

## No fabricated metrics
Overview exposes `unavailable: [dau, mau, engagement_rate]` (no session/event model). No risk/toxicity/
trust/effectiveness scores anywhere. Boost observability shows real type/weight/status only — no
effectiveness/reach/impressions.

## Tests
`social-a2.test.ts` asserts no saver reader; agent detail has no owner field; author_type preserved;
`social-a2-investigation.test.ts` asserts partial-failure isolation + provenance.
