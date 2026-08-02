import { socialRead, idFromUrl } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.post.read", "feed.read", (req, ctx) =>
  SocialControlPlane.getPost(ctx, idFromUrl(req.url)),
);
