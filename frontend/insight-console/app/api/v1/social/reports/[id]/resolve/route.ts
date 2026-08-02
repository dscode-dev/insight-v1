import { socialCommand } from "@/lib/control-plane/social-command";
import { SocialEnforcement } from "@/lib/control-plane/adapters/social-enforcement";
export const dynamic = "force-dynamic";
export const POST = socialCommand("trust.report.resolve", "feed.hide", (id, input, ctx) => SocialEnforcement.resolveReport(ctx, id, input));
