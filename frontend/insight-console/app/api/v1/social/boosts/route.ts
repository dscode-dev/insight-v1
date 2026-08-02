import { socialRead } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.boost.read", "feed.read", (req, ctx) => {
  const p = new URL(req.url).searchParams;
  return SocialControlPlane.listBoosts(ctx, { limit: p.get("limit") ?? undefined, cursor: p.get("cursor") ?? undefined, post_id: p.get("post_id") ?? undefined, user_id: p.get("user_id") ?? undefined, status: p.get("status") ?? undefined });
});
