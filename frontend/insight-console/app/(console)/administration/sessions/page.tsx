import { AdminSessions } from "@/components/console/admin-center";

export const dynamic = "force-dynamic";

export default function AdminSessionsPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <AdminSessions />
    </div>
  );
}
