// Notification gRPC handler. Translate → app service → map error. No business
// logic. Read/mark only; creation flows through the domain Publisher seam.
package grpc

import (
	"context"
	"errors"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	appnotif "github.com/konoha-labs/insight-social/internal/application/notification"
	domnotif "github.com/konoha-labs/insight-social/internal/domain/notification"
)

type NotificationServer struct {
	socialv1.UnimplementedNotificationServiceServer
	svc *appnotif.Service
}

func NewNotificationServer(svc *appnotif.Service) *NotificationServer {
	return &NotificationServer{svc: svc}
}

func (s *NotificationServer) List(ctx context.Context, req *socialv1.ListNotificationsRequest) (*socialv1.ListNotificationsResponse, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	limit := 0
	if req.Limit != nil {
		limit = int(req.GetLimit())
	}
	cursor := ""
	if req.Cursor != nil {
		cursor = req.GetCursor()
	}
	unreadOnly := false
	if req.UnreadOnly != nil {
		unreadOnly = req.GetUnreadOnly()
	}
	page, err := s.svc.List(ctx, userID, limit, cursor, unreadOnly)
	if err != nil {
		return nil, mapNotifErr(err)
	}
	out := make([]*socialv1.Notification, 0, len(page.Notifications))
	for _, n := range page.Notifications {
		out = append(out, notificationToProto(n))
	}
	resp := &socialv1.ListNotificationsResponse{Notifications: out}
	if page.NextCursor != "" {
		resp.NextCursor = &page.NextCursor
	}
	return resp, nil
}

func (s *NotificationServer) UnreadCount(ctx context.Context, req *socialv1.UnreadCountRequest) (*socialv1.UnreadCountResponse, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	n, err := s.svc.UnreadCount(ctx, userID)
	if err != nil {
		return nil, mapNotifErr(err)
	}
	return &socialv1.UnreadCountResponse{UnreadCount: n}, nil
}

func (s *NotificationServer) MarkRead(ctx context.Context, req *socialv1.MarkReadRequest) (*socialv1.MarkReadResponse, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	changed, unread, err := s.svc.MarkRead(ctx, userID, id)
	if err != nil {
		return nil, mapNotifErr(err)
	}
	return &socialv1.MarkReadResponse{Changed: changed, UnreadCount: unread}, nil
}

func (s *NotificationServer) MarkAllRead(ctx context.Context, req *socialv1.MarkAllReadRequest) (*socialv1.MarkAllReadResponse, error) {
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	marked, unread, err := s.svc.MarkAllRead(ctx, userID)
	if err != nil {
		return nil, mapNotifErr(err)
	}
	return &socialv1.MarkAllReadResponse{Marked: marked, UnreadCount: unread}, nil
}

// ---- translators ----

func notificationToProto(n *domnotif.Notification) *socialv1.Notification {
	out := &socialv1.Notification{
		Id:          n.ID().String(),
		UserId:      n.UserID().String(),
		Type:        notifTypeToProto(n.Type()),
		Priority:    notifPriorityToProto(n.Priority()),
		Status:      notifStatusToProto(n.Status()),
		Title:       n.Title(),
		Body:        n.Body(),
		TargetType:  n.Target().Type,
		Deeplink:    n.Target().DeepLink,
		PayloadJson: string(n.Payload()),
		CreatedAt:   timestamppb.New(n.CreatedAt()),
	}
	if tid := n.Target().ID; tid != nil {
		s := tid.String()
		out.TargetId = &s
	}
	if ra := n.ReadAt(); ra != nil {
		out.ReadAt = timestamppb.New(*ra)
	}
	return out
}

func notifTypeToProto(t domnotif.Type) socialv1.NotificationType {
	switch t {
	case domnotif.TypeCommunityJoin:
		return socialv1.NotificationType_NOTIFICATION_TYPE_COMMUNITY_JOIN
	case domnotif.TypeDiscussionReply:
		return socialv1.NotificationType_NOTIFICATION_TYPE_DISCUSSION_REPLY
	case domnotif.TypeMention:
		return socialv1.NotificationType_NOTIFICATION_TYPE_MENTION
	case domnotif.TypeReaction:
		return socialv1.NotificationType_NOTIFICATION_TYPE_REACTION
	case domnotif.TypeSystem:
		return socialv1.NotificationType_NOTIFICATION_TYPE_SYSTEM
	default:
		return socialv1.NotificationType_NOTIFICATION_TYPE_UNSPECIFIED
	}
}

func notifPriorityToProto(p domnotif.Priority) socialv1.NotificationPriority {
	switch p {
	case domnotif.PriorityLow:
		return socialv1.NotificationPriority_NOTIFICATION_PRIORITY_LOW
	case domnotif.PriorityHigh:
		return socialv1.NotificationPriority_NOTIFICATION_PRIORITY_HIGH
	default:
		return socialv1.NotificationPriority_NOTIFICATION_PRIORITY_NORMAL
	}
}

func notifStatusToProto(s domnotif.Status) socialv1.NotificationStatus {
	if s == domnotif.StatusRead {
		return socialv1.NotificationStatus_NOTIFICATION_STATUS_READ
	}
	return socialv1.NotificationStatus_NOTIFICATION_STATUS_UNREAD
}

func mapNotifErr(err error) error {
	switch {
	case errors.Is(err, domnotif.ErrNotFound):
		return status.Error(codes.NotFound, "notification not found")
	case errors.Is(err, domnotif.ErrInvalidCursor):
		return status.Error(codes.InvalidArgument, err.Error())
	case errors.Is(err, domnotif.ErrInvalidType),
		errors.Is(err, domnotif.ErrInvalidUser),
		errors.Is(err, domnotif.ErrEmptyTitle),
		errors.Is(err, domnotif.ErrEmptyDedupKey):
		return status.Error(codes.InvalidArgument, err.Error())
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
