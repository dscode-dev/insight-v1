// FEATURE-NOTIFICATIONS-V1 Stage 2 — Social boundary + proto→DTO mapping.
//
// SocialGateway is the internal seam (fakeable in tests). The real adapter
// wraps the social.v1 gRPC NotificationService. Mapping proto → public DTO —
// including the Gateway-owned presentation hints (icon/color), per-notification
// capabilities, deep-link validation and payload decoding — happens ONLY here.
package notificationbff

import (
	"context"
	"encoding/json"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
)

type SocialGateway interface {
	List(ctx context.Context, userID, cursor string, limit int32, unreadOnly bool) (*socialv1.ListNotificationsResponse, error)
	UnreadCount(ctx context.Context, userID string) (int64, error)
	MarkRead(ctx context.Context, userID, id string) (*socialv1.MarkReadResponse, error)
	MarkAllRead(ctx context.Context, userID string) (*socialv1.MarkAllReadResponse, error)
}

type grpcGateway struct {
	c socialv1.NotificationServiceClient
}

func NewGRPCGateway(c socialv1.NotificationServiceClient) SocialGateway { return &grpcGateway{c: c} }

func (g *grpcGateway) List(ctx context.Context, userID, cursor string, limit int32, unreadOnly bool) (*socialv1.ListNotificationsResponse, error) {
	req := &socialv1.ListNotificationsRequest{UserId: userID}
	if limit > 0 {
		req.Limit = &limit
	}
	if cursor != "" {
		req.Cursor = &cursor
	}
	if unreadOnly {
		u := true
		req.UnreadOnly = &u
	}
	return g.c.List(ctx, req)
}

func (g *grpcGateway) UnreadCount(ctx context.Context, userID string) (int64, error) {
	resp, err := g.c.UnreadCount(ctx, &socialv1.UnreadCountRequest{UserId: userID})
	if err != nil {
		return 0, err
	}
	return resp.UnreadCount, nil
}

func (g *grpcGateway) MarkRead(ctx context.Context, userID, id string) (*socialv1.MarkReadResponse, error) {
	return g.c.MarkRead(ctx, &socialv1.MarkReadRequest{UserId: userID, Id: id})
}

func (g *grpcGateway) MarkAllRead(ctx context.Context, userID string) (*socialv1.MarkAllReadResponse, error) {
	return g.c.MarkAllRead(ctx, &socialv1.MarkAllReadRequest{UserId: userID})
}

// ---- proto → DTO ----

func typeToWire(t socialv1.NotificationType) string {
	switch t {
	case socialv1.NotificationType_NOTIFICATION_TYPE_COMMUNITY_JOIN:
		return "community_join"
	case socialv1.NotificationType_NOTIFICATION_TYPE_DISCUSSION_REPLY:
		return "discussion_reply"
	case socialv1.NotificationType_NOTIFICATION_TYPE_MENTION:
		return "mention"
	case socialv1.NotificationType_NOTIFICATION_TYPE_REACTION:
		return "reaction"
	case socialv1.NotificationType_NOTIFICATION_TYPE_SYSTEM:
		return "system"
	default:
		return "system"
	}
}

func priorityToWire(p socialv1.NotificationPriority) string {
	switch p {
	case socialv1.NotificationPriority_NOTIFICATION_PRIORITY_LOW:
		return "low"
	case socialv1.NotificationPriority_NOTIFICATION_PRIORITY_HIGH:
		return "high"
	default:
		return "normal"
	}
}

// presentation is the Gateway-owned icon+color for a type. Changing a type's
// look is a one-line change HERE, never in the client.
type presentation struct{ icon, color string }

var typePresentation = map[string]presentation{
	"community_join":   {"person_add", "#56C596"},
	"discussion_reply": {"reply", "#5BA8FF"},
	"mention":          {"alternate_email", "#FFC857"},
	"reaction":         {"favorite", "#FF6B9D"},
	"system":           {"campaign", "#B388EB"},
}

func presentationFor(typeWire string) presentation {
	if p, ok := typePresentation[typeWire]; ok {
		return p
	}
	return presentation{"notifications", "#5BA8FF"}
}

// notificationToDTO maps one proto notification to the public DTO: validates
// the deeplink (invalid → dropped + can_open=false, notification kept), assigns
// icon/color, derives capabilities, decodes the opaque payload.
func notificationToDTO(n *socialv1.Notification) Notification {
	typeWire := typeToWire(n.Type)
	pres := presentationFor(typeWire)
	deeplink := validDeepLink(n.Deeplink)
	read := n.Status == socialv1.NotificationStatus_NOTIFICATION_STATUS_READ

	out := Notification{
		ID:       n.Id,
		Type:     typeWire,
		Priority: priorityToWire(n.Priority),
		Title:    n.Title,
		Body:     n.Body,
		Icon:     pres.icon,
		Color:    pres.color,
		DeepLink: deeplink,
		Read:     read,
		Capabilities: NotificationCaps{
			CanOpen:     deeplink != "",
			CanMarkRead: !read,
			CanDelete:   false, // V1
			CanArchive:  false, // V1
			CanShare:    false, // V1
		},
	}
	if n.CreatedAt != nil {
		out.CreatedAt = n.CreatedAt.AsTime().UTC().Format("2006-01-02T15:04:05Z07:00")
	}
	if n.PayloadJson != "" && n.PayloadJson != "{}" {
		var m map[string]any
		if err := json.Unmarshal([]byte(n.PayloadJson), &m); err == nil {
			out.Payload = m
		}
	}
	return out
}
