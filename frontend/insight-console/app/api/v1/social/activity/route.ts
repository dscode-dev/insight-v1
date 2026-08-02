import { socialRead } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.activity.read", "feed.read", (req, ctx) => {
  const p = new URL(req.url).searchParams;
  return SocialControlPlane.activity(ctx, { limit: p.get("limit") ?? undefined, cursor: p.get("cursor") ?? undefined, kind: p.get("kind") ?? undefined });
});
