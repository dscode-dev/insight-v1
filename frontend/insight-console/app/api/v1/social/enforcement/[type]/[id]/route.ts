import { socialRead } from "@/lib/control-plane/social-bff";
import { enforcementState } from "@/lib/control-plane/adapters/social-enforcement";
export const dynamic = "force-dynamic";
export const GET = socialRead("social.moderation.read", "feed.read", (req, ctx) => {
  const parts = new URL(req.url).pathname.split("/").filter(Boolean);
  const id = decodeURIComponent(parts[parts.length - 1] ?? "");
  const type = decodeURIComponent(parts[parts.length - 2] ?? "");
  return enforcementState(ctx, type, id);
});
