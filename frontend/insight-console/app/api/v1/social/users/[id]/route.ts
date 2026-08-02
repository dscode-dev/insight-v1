import { socialRead, idFromUrl } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.user.read", "user.read", (req, ctx) =>
  SocialControlPlane.getUser(ctx, idFromUrl(req.url)),
);
