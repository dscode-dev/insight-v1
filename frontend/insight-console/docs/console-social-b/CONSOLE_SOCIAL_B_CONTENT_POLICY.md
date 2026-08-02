# CONSOLE-SOCIAL-B — Content Visibility Policy

## Model
Hidden state is Gateway-owned (`moderation_hidden_content`, PK (target_type,target_id)). A hidden
post/comment is NOT deleted. Two read models:
- **Consumer read model**: hidden content excluded. Enforced by `ViewFor` post-filtering of proxied
  Social responses.
- **Operator investigation read model**: hidden content remains inspectable (with its moderation state).

## Consumer surfaces the hidden filter now covers
- Global/following feed ✓ (pre-existing) · comments list ✓ (pre-existing) · author/profile posts ✓
  (pre-existing) · **single post detail ✓ (added — hidden ⇒ 404, not leaked)**.
- Also excludes non-active authors' content (author-hidden) on all the above.
- Saved-posts / discovery: saved rows reference posts; a hidden post surfaced via saved list is subject
  to the same author/post hidden filter where the feed projection is applied. (Direct saved-list rows
  are id references; hiding is enforced when the post is fetched/rendered through a filtered path.)

## Thread integrity
Hiding a parent comment removes it from the consumer projection; replies are **not** cascade-hidden and
their text is **not** fabricated/tombstoned into fake content — the structure is preserved and each
comment is hidden explicitly. Operators still see the full thread.

## Reversal
`restore` clears the hidden row (idempotent); content reappears on consumer surfaces. Reason mandatory;
domain + canonical audit recorded.
