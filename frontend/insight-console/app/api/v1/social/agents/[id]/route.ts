import { socialRead, idFromUrl } from "@/lib/control-plane/social-bff";
import { SocialControlPlane } from "@/lib/control-plane/adapters/social";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.agent.read", "user.read", (req, ctx) =>
  SocialControlPlane.getAgent(ctx, idFromUrl(req.url)),
);
