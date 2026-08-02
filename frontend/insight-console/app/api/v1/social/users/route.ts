import { socialRead } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.user.read", "user.read", (req, ctx) => {
  const p = new URL(req.url).searchParams;
  return SocialControlPlane.listUsers(ctx, { limit: p.get("limit") ?? undefined, cursor: p.get("cursor") ?? undefined, q: p.get("q") ?? undefined });
});
