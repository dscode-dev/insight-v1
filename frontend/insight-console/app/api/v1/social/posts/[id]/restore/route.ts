import { governedSocialCommand } from "@/lib/control-plane/social-command";
export const dynamic = "force-dynamic";
export const POST = governedSocialCommand("social.content.restore", "feed.restore", "post");
