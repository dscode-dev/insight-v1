// CONSOLE-IDENTITY-A — Operational Identity & Delegation (admin, read-first).
// Shows the current operator's server-resolved provenance chain and their grants.
// Does NOT redesign existing UX, touch the Investigation Plane, or Social
// Enforcement. Data comes exclusively from the server-owned BFF (Gateway authority).

import { requireOperator } from "@/lib/api-guard";
import { readSessionCookie } from "@/lib/session";
import { listDelegations, resolveOperationalIdentity } from "@/lib/control-plane/adapters/identity";
import { ProvenanceChain } from "@/components/identity/ProvenanceChain";

export const dynamic = "force-dynamic";

export default async function IdentityPage() {
  await requireOperator();
  const token = readSessionCookie();
  const [resolved, grants] = await Promise.all([
    resolveOperationalIdentity(token, null).catch(() => null),
    listDelegations(token, null).catch(() => []),
  ]);

  return (
    <div className="flex flex-col gap-6 p-6">
      <div>
        <h1 className="text-lg font-semibold">Operational Identity</h1>
        <p className="text-sm text-muted-foreground">
          Server-resolved provenance. The authenticated operator is always preserved (executed_by),
          even under delegation.
        </p>
      </div>

      {resolved ? (
        <ProvenanceChain
          data={{
            executedBy: resolved.executedBy,
            operatorId: resolved.operatorId,
            identityId: resolved.identityId,
            identityKind: resolved.identityKind,
            publicActor: resolved.publicActor,
            delegation: resolved.delegation
              ? {
                  delegationId: resolved.delegation.delegationId,
                  subjectType: resolved.delegation.subjectType,
                  subjectId: resolved.delegation.subjectId,
                }
              : null,
          }}
        />
      ) : (
        <p className="text-sm text-muted-foreground">Identity resolution unavailable right now.</p>
      )}

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold">Delegation grants</h2>
        {grants.length === 0 ? (
          <p className="text-sm text-muted-foreground">
            No delegation grants. You are acting as yourself.
          </p>
        ) : (
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="bg-muted/50 text-left text-xs uppercase text-muted-foreground">
                <tr>
                  <th className="p-2">Subject</th>
                  <th className="p-2">Mode</th>
                  <th className="p-2">Reason</th>
                  <th className="p-2">Public actor</th>
                  <th className="p-2">Status</th>
                </tr>
              </thead>
              <tbody>
                {grants.map((g) => (
                  <tr key={g.delegationId} className="border-t border-border">
                    <td className="p-2">{g.subjectType}:{g.subjectId}</td>
                    <td className="p-2">{g.mode}</td>
                    <td className="p-2">{g.reason}</td>
                    <td className="p-2">{g.publicActor ?? "—"}</td>
                    <td className="p-2">{g.active ? "active" : "inactive"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  );
}
