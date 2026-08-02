import { socialRead } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.community.read", "feed.read", (req, ctx) => SocialControlPlane.listCommunities(ctx, { limit: new URL(req.url).searchParams.get("limit") ?? undefined }));
