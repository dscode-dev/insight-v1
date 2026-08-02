package console

// Role normalization + permission sets, mirroring the operator auth handler so
// the admin/operators surface reports the same effective permissions the
// operator session resolves to. (Kept in sync with
// internal/interfaces/http/operator/handlers.go.)

func NormalizeRole(role string) string {
	switch role {
	case "super_admin", "SuperAdmin", "PlatformAdmin":
		return "SuperAdmin"
	case "admin", "Operations":
		return "Operations"
	case "operator", "Support":
		return "Support"
	case "analyst", "Analyst":
		return "Analyst"
	default:
		return "ReadOnly"
	}
}

func PermissionsForRole(role string) []string {
	read := []string{"console.access", "feed.read", "user.read", "model.read", "dlq.read", "audit.read", "flag.read", "config.read", "scheduler.read"}
	switch role {
	case "SuperAdmin":
		return append([]string{"incident.manage"}, []string{"user.read", "user.suspend", "user.ban", "user.shadow_ban", "user.force_logout", "user.invalidate_sessions", "user.change_permissions", "user.flag_for_audit", "user.add_notes", "feed.read", "feed.hide", "feed.delete", "feed.restore", "feed.mark_sensitive", "scheduler.read", "scheduler.pause", "scheduler.resume", "scheduler.force_sync", "provider.read", "provider.enable", "provider.disable", "provider.maintenance", "provider.force_sync", "model.read", "model.promote", "model.rollback", "model.pause_consumer", "model.resume_consumer", "model.enable_family", "model.disable_family", "model.clear_cache", "dlq.read", "dlq.replay", "dlq.archive", "dlq.mark_resolved", "audit.read", "flag.read", "flag.write", "config.read", "config.write", "maintenance_mode.toggle", "console.access"}...)
	case "Operations":
		return append(read, "incident.manage", "scheduler.pause", "scheduler.resume", "scheduler.force_sync", "provider.enable", "provider.disable", "dlq.replay")
	case "Support":
		return append(read, "user.add_notes", "user.flag_for_audit")
	default:
		return read
	}
}
