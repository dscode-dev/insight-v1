import { governedSocialCommand } from "@/lib/control-plane/social-command";
export const dynamic = "force-dynamic";
export const POST = governedSocialCommand("social.content.hide", "feed.hide", "comment");
