"use client";

import { Bell } from "lucide-react";

export function NotificationsBell() {
  return (
    <button
      type="button"
      className="rounded-md p-2 text-muted-foreground"
      aria-label="Notifications"
      disabled
    >
      <Bell className="h-4 w-4" />
    </button>
  );
}
