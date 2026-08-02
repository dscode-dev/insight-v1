import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { ConsoleApiError } from "@/lib/admin-api";
import { robozaoIncidentCommand, robozaoOps } from "@/lib/robozao";

export const dynamic = "force-dynamic";

export const GET = withApiHandler(async (req: Request) => {
  await requirePermission("console.access");
  const url = new URL(req.url);
  const query = new URLSearchParams();
  for (const key of ["service", "status", "limit"]) {
    const value = url.searchParams.get(key);
    if (value) query.set(key, value);
  }
  return Response.json(await robozaoOps("incidents", query.toString()));
});

export const POST = withApiHandler(async (req: Request) => {
  await requirePermission("incident.manage");
  const body = await req.json().catch(() => null);
  if (!body || typeof body !== "object") {
    throw new ConsoleApiError(400, "invalid_incident_body");
  }
  const result = await robozaoIncidentCommand("/operations/incidents", body);
  return Response.json(result, { status: 201 });
});
