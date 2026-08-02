import { requirePermission, withApiHandler } from "@/lib/api-guard";
import { ConsoleApiError } from "@/lib/admin-api";
import { robozaoIncidentCommand } from "@/lib/robozao";

const ACTIONS = new Set(["acknowledge", "assign", "resolve"]);

export const POST = withApiHandler(async (req: Request) => {
  await requirePermission("incident.manage");
  const segments = new URL(req.url).pathname.split("/").filter(Boolean);
  const action = segments[segments.length - 1] ?? "";
  const id = segments[segments.length - 2] ?? "";
  if (!/^[a-zA-Z0-9-]+$/.test(id) || !ACTIONS.has(action)) {
    throw new ConsoleApiError(400, "invalid_incident_action");
  }
  const body = await req.json().catch(() => ({}));
  return Response.json(
    await robozaoIncidentCommand(
      `/operations/incidents/${id}/${action}`,
      body,
    ),
  );
});
