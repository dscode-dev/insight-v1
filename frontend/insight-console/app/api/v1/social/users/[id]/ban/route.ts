import { socialCommand } from "@/lib/control-plane/social-command";
import { SocialEnforcement } from "@/lib/control-plane/adapters/social-enforcement";
export const dynamic = "force-dynamic";
export const POST = socialCommand("social.user.ban", "user.ban", (id, input, ctx) => SocialEnforcement.banUser(ctx, id, input));
