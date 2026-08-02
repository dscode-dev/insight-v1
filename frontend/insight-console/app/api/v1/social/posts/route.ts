import { socialRead } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.post.read", "feed.read", (req, ctx) => {
  const p = new URL(req.url).searchParams;
  return SocialControlPlane.listPosts(ctx, {
    limit: p.get("limit") ?? undefined, cursor: p.get("cursor") ?? undefined,
    author_type: p.get("author_type") ?? undefined, author_id: p.get("author_id") ?? undefined,
    boosted: p.get("boosted") ?? undefined,
  });
});
