import { socialRead } from "@/lib/control-plane/social-bff";
import { GatewayTrustSafety } from "@/lib/control-plane/adapters/trust-safety";
export const dynamic = "force-dynamic";
export const GET = socialRead("trust.report.read", "feed.read", (req) => {
  const p = new URL(req.url).searchParams;
  const qparts: string[] = [];
  const status = p.get("status"); if (status) qparts.push(`status=${encodeURIComponent(status)}`);
  qparts.push(`limit=${p.get("limit") ?? "100"}`);
  return GatewayTrustSafety.reports(qparts.join("&"));
});
