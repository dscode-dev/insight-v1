import { AdminUsers } from "@/components/console/admin-center";

export const dynamic = "force-dynamic";

export default function AdminUsersPage() {
  return (
    <div className="mx-auto max-w-6xl">
      <AdminUsers />
    </div>
  );
}
