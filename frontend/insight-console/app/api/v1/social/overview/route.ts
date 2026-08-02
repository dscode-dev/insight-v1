import { socialRead } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.overview.read", "feed.read", (req, ctx) =>
  SocialControlPlane.overview(ctx, new URL(req.url).searchParams.get("window") ?? undefined),
);
