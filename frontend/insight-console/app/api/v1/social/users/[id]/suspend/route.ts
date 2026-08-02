import { socialCommand } from "@/lib/control-plane/social-command";
import { SocialEnforcement } from "@/lib/control-plane/adapters/social-enforcement";
export const dynamic = "force-dynamic";
export const POST = socialCommand("social.user.suspend", "user.suspend", (id, input, ctx) => SocialEnforcement.suspendUser(ctx, id, input));
