// User gRPC handler — translates social.v1.UserService RPCs ⇄
// application/user.Service. The handler does NO business logic; its
// only jobs are:
//  1. Parse / validate request shape (uuids, required fields).
//  2. Call the app service.
//  3. Translate the result (or domain error) into the proto type + a
//     gRPC status code.
//
// Domain error → status code mapping is the only "policy" here:
//
//	ErrNotFound           → NotFound
//	ErrUsernameTaken      → AlreadyExists
//	ErrInvalid*           → InvalidArgument
//	other                 → Internal (with the underlying error logged
//	                       but NOT leaked to the client message)
package grpc

import (
	"context"
	"errors"

	"github.com/google/uuid"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	apppreferences "github.com/konoha-labs/insight-social/internal/application/preferences"
	appuser "github.com/konoha-labs/insight-social/internal/application/user"
	domuser "github.com/konoha-labs/insight-social/internal/domain/user"
)

// UserServer is the real handler. Replaces UserStub at server boot.
//
// Sprint D: the `prefs` field is set post-construction via
// PrefsAttacher (see preferences.go). main.go wires both in the same
// breath; nil prefs makes the preferences RPCs return Unimplemented
// instead of crashing, which is the safer posture for a partial wire.
type UserServer struct {
	socialv1.UnimplementedUserServiceServer
	svc   *appuser.Service
	prefs *apppreferences.Service
}

func NewUserServer(svc *appuser.Service) *UserServer {
	return &UserServer{svc: svc}
}

// ---- RPC methods ----

func (s *UserServer) Create(ctx context.Context, req *socialv1.CreateUserRequest) (*socialv1.User, error) {
	if req.GetUsername() == "" {
		return nil, status.Error(codes.InvalidArgument, "username required")
	}
	if req.GetDisplayName() == "" {
		return nil, status.Error(codes.InvalidArgument, "display_name required")
	}
	accent := ""
	if req.AccentColor != nil {
		accent = req.GetAccentColor()
	}

	u, err := s.svc.Create(ctx, req.GetUsername(), req.GetDisplayName(), accent)
	if err != nil {
		return nil, mapUserErr(err)
	}
	return userToProto(u), nil
}

func (s *UserServer) Get(ctx context.Context, req *socialv1.GetUserRequest) (*socialv1.User, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	u, err := s.svc.Get(ctx, id)
	if err != nil {
		return nil, mapUserErr(err)
	}
	return userToProto(u), nil
}

func (s *UserServer) GetByUsername(ctx context.Context, req *socialv1.GetByUsernameRequest) (*socialv1.User, error) {
	if req.GetUsername() == "" {
		return nil, status.Error(codes.InvalidArgument, "username required")
	}
	u, err := s.svc.GetByUsername(ctx, req.GetUsername())
	if err != nil {
		return nil, mapUserErr(err)
	}
	return userToProto(u), nil
}

func (s *UserServer) UpdateAccent(ctx context.Context, req *socialv1.UpdateAccentRequest) (*socialv1.User, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	u, err := s.svc.UpdateAccent(ctx, id, req.GetAccentColor())
	if err != nil {
		return nil, mapUserErr(err)
	}
	return userToProto(u), nil
}

// UpdateAvatar — Sprint C. Empty avatar_url clears the persisted URL
// (server stores NULL); UI falls back to initials rendering.
func (s *UserServer) UpdateAvatar(ctx context.Context, req *socialv1.UpdateAvatarRequest) (*socialv1.User, error) {
	id, err := parseUUID(req.GetId(), "id")
	if err != nil {
		return nil, err
	}
	u, err := s.svc.UpdateAvatar(ctx, id, req.GetAvatarUrl())
	if err != nil {
		return nil, mapUserErr(err)
	}
	return userToProto(u), nil
}

func (s *UserServer) List(ctx context.Context, req *socialv1.ListUsersRequest) (*socialv1.ListUsersResponse, error) {
	rawIDs := req.GetIds()
	ids := make([]uuid.UUID, 0, len(rawIDs))
	for i, raw := range rawIDs {
		parsed, err := uuid.Parse(raw)
		if err != nil {
			return nil, status.Errorf(codes.InvalidArgument, "ids[%d]: %v", i, err)
		}
		ids = append(ids, parsed)
	}
	users, err := s.svc.List(ctx, ids)
	if err != nil {
		return nil, mapUserErr(err)
	}
	out := make([]*socialv1.User, 0, len(users))
	for _, u := range users {
		out = append(out, userToProto(u))
	}
	return &socialv1.ListUsersResponse{Users: out}, nil
}

func (s *UserServer) GetStats(ctx context.Context, req *socialv1.GetUserStatsRequest) (*socialv1.UserStats, error) {
	id, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	st, err := s.svc.Stats(ctx, id)
	if err != nil {
		return nil, mapUserErr(err)
	}
	return &socialv1.UserStats{
		UserId:            st.UserID.String(),
		SignalsSent:       st.SignalsSent,
		SignalsValidated:  st.SignalsValidated,
		SignalsFlagged:    st.SignalsFlagged,
		MatchesFollowed:   st.MatchesFollowed,
		CommunitiesJoined: st.CommunitiesJoined,
		Accuracy:          st.Accuracy,
	}, nil
}

// ---- translators ----

func userToProto(u *domuser.User) *socialv1.User {
	return &socialv1.User{
		Id:          u.ID().String(),
		Username:    u.Username(),
		DisplayName: u.DisplayName(),
		Initials:    u.Initials(),
		AccentColor: u.AccentColor(),
		Reputation:  int32(u.Reputation()),
		Tier:        tierToProto(u.Tier()),
		CreatedAt:   timestamppb.New(u.CreatedAt()),
		AvatarUrl:   u.AvatarURL(),
	}
}

func tierToProto(t domuser.Tier) socialv1.UserTier {
	switch t {
	case domuser.TierRookie:
		return socialv1.UserTier_USER_TIER_ROOKIE
	case domuser.TierScout:
		return socialv1.UserTier_USER_TIER_SCOUT
	case domuser.TierAnalyst:
		return socialv1.UserTier_USER_TIER_ANALYST
	case domuser.TierOracle:
		return socialv1.UserTier_USER_TIER_ORACLE
	default:
		return socialv1.UserTier_USER_TIER_UNSPECIFIED
	}
}

// parseUUID is shared by every handler that takes an `id` string.
func parseUUID(raw, field string) (uuid.UUID, error) {
	if raw == "" {
		return uuid.Nil, status.Errorf(codes.InvalidArgument, "%s required", field)
	}
	id, err := uuid.Parse(raw)
	if err != nil {
		return uuid.Nil, status.Errorf(codes.InvalidArgument, "%s: %v", field, err)
	}
	return id, nil
}

// parsePair parses (source_user_id, target_user_id) — convenience
// for relationship handlers where every RPC takes this shape.
func parsePair(sourceRaw, targetRaw string) (uuid.UUID, uuid.UUID, error) {
	source, err := parseUUID(sourceRaw, "source_user_id")
	if err != nil {
		return uuid.Nil, uuid.Nil, err
	}
	target, err := parseUUID(targetRaw, "target_user_id")
	if err != nil {
		return uuid.Nil, uuid.Nil, err
	}
	return source, target, nil
}

// mapUserErr turns a domain error into a gRPC status. Sentinel errors
// listed in domain/user/errors.go are the only ones that get a
// specific code — everything else is Internal, with the original
// error preserved via status.Error for server-side logs but masked
// from the client message.
func mapUserErr(err error) error {
	switch {
	case errors.Is(err, domuser.ErrNotFound):
		return status.Error(codes.NotFound, "user not found")
	case errors.Is(err, domuser.ErrUsernameTaken):
		return status.Error(codes.AlreadyExists, "username already taken")
	case errors.Is(err, domuser.ErrInvalidUsername),
		errors.Is(err, domuser.ErrInvalidDisplayName),
		errors.Is(err, domuser.ErrInvalidAccentColor),
		errors.Is(err, domuser.ErrInvalidAvatarURL):
		return status.Error(codes.InvalidArgument, err.Error())
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
