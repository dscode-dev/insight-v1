import { socialRead } from "@/lib/control-plane/social-bff";
import { GatewayTrustSafety } from "@/lib/control-plane/adapters/trust-safety";
export const dynamic = "force-dynamic";
export const GET = socialRead("trust.moderation.read", "feed.read", (req) =>
  GatewayTrustSafety.actions(Number(new URL(req.url).searchParams.get("limit") ?? "100")));
