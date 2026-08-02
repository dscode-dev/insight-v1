import { socialCommand } from "@/lib/control-plane/social-command";
import { SocialEnforcement } from "@/lib/control-plane/adapters/social-enforcement";
export const dynamic = "force-dynamic";
export const POST = socialCommand("trust.report.dismiss", "feed.hide", (id, input, ctx) => SocialEnforcement.dismissReport(ctx, id, input));
