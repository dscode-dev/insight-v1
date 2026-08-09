// FEATURE-NOTIFICATIONS-V1 Stage 2 — Notification Orchestrator public contract.
//
// These DTOs are the DEFINITIVE public contract. They are Gateway-owned and do
// NOT reuse the social.v1 proto structs — Social may evolve internally without
// breaking clients. The Gateway also owns the PRESENTATION hints (icon + color)
// so the client renders without knowing Social's internal enums: if a type's
// visual representation changes later, only the Gateway changes.
package notificationbff

// Notification is one public notification row.
type Notification struct {
	ID           string           `json:"id"`
	Type         string           `json:"type"`     // community_join|discussion_reply|mention|reaction|system
	Priority     string           `json:"priority"` // low|normal|high
	Title        string           `json:"title"`
	Body         string           `json:"body"`
	Icon         string           `json:"icon"`      // presentation hint (Gateway-owned)
	Color        string           `json:"color"`     // presentation hint (hex, Gateway-owned)
	DeepLink     string           `json:"deep_link"` // "" when absent/invalid — action removed, notif kept
	CreatedAt    string           `json:"created_at"`
	Read         bool             `json:"read"`
	Payload      map[string]any   `json:"payload,omitempty"`
	Capabilities NotificationCaps `json:"capabilities"`
}

// NotificationCaps are per-notification capabilities. The client renders
// actions ONLY from these — never inferred. Several are constant-false in V1
// but present so future evolution never breaks the client.
type NotificationCaps struct {
	CanOpen     bool `json:"can_open"`      // deeplink valid
	CanMarkRead bool `json:"can_mark_read"` // currently unread
	CanDelete   bool `json:"can_delete"`    // false in V1
	CanArchive  bool `json:"can_archive"`   // false in V1
	CanShare    bool `json:"can_share"`     // false in V1
}

// ListResponse is the Notification Center page. It carries next_cursor +
// has_more (never make the client infer) and the unread_count (so opening the
// center refreshes the badge in ONE call). partial=true when a non-critical
// section (unread_count) failed while the list itself loaded.
type ListResponse struct {
	Items          []Notification `json:"items"`
	NextCursor     string         `json:"next_cursor"`
	HasMore        bool           `json:"has_more"`
	UnreadCount    int64          `json:"unread_count"`
	Partial        bool           `json:"partial"`
	FailedSections []string       `json:"failed_sections,omitempty"`
}

type UnreadCountResponse struct {
	UnreadCount int64 `json:"unread_count"`
}

// MarkReadResponse returns the UPDATED notification + refreshed unread_count so
// the client needs no second call.
type MarkReadResponse struct {
	Changed      bool          `json:"changed"`
	Notification *Notification `json:"notification,omitempty"`
	UnreadCount  int64         `json:"unread_count"`
}

type MarkAllReadResponse struct {
	Marked      int64 `json:"marked"`
	UnreadCount int64 `json:"unread_count"`
}
