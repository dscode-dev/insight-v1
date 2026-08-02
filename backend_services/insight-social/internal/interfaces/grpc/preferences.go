// Sprint D — preferences gRPC handlers, attached to UserServiceServer.
//
// The RPCs live on UserService in the proto (preferences are User
// concerns) but the application service is independent in Go to keep
// the User application service free of cross-table concerns.
package grpc

import (
	"context"
	"errors"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"
	"google.golang.org/protobuf/types/known/timestamppb"

	apppreferences "github.com/konoha-labs/insight-social/internal/application/preferences"
	dompreferences "github.com/konoha-labs/insight-social/internal/domain/preferences"
)

// PrefsAttacher attaches the GetPreferences + UpdatePreferences
// handlers to an existing UserServer. The single proto service stays
// satisfied by one Go type, but the field is set after construction
// so the wiring stays explicit in main.go.
type PrefsAttacher struct {
	svc *apppreferences.Service
}

func NewPrefsAttacher(svc *apppreferences.Service) *PrefsAttacher {
	return &PrefsAttacher{svc: svc}
}

// AttachTo enriches the supplied UserServer with the preferences
// handlers. Called from main.go after both servers exist.
func (a *PrefsAttacher) AttachTo(server *UserServer) {
	server.prefs = a.svc
}

// The actual RPC methods live on UserServer (defined in user.go).
// We add them here so the preference logic stays co-located with the
// rest of Sprint D's gRPC translation.

func (s *UserServer) GetPreferences(ctx context.Context, req *socialv1.GetPreferencesRequest) (*socialv1.UserPreferences, error) {
	if s.prefs == nil {
		return nil, status.Error(codes.Unimplemented, "preferences not wired")
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	p, err := s.prefs.Get(ctx, userID)
	if err != nil {
		return nil, mapPrefsErr(err)
	}
	return preferencesToProto(p), nil
}

func (s *UserServer) UpdatePreferences(ctx context.Context, req *socialv1.UpdatePreferencesRequest) (*socialv1.UserPreferences, error) {
	if s.prefs == nil {
		return nil, status.Error(codes.Unimplemented, "preferences not wired")
	}
	userID, err := parseUUID(req.GetUserId(), "user_id")
	if err != nil {
		return nil, err
	}
	patch := dompreferences.Update{}
	if req.Locale != nil {
		v := req.GetLocale()
		patch.Locale = &v
	}
	if req.PushEnabled != nil {
		v := req.GetPushEnabled()
		patch.PushEnabled = &v
	}
	if req.EmailEnabled != nil {
		v := req.GetEmailEnabled()
		patch.EmailEnabled = &v
	}
	if req.DigestFrequency != nil {
		v := req.GetDigestFrequency()
		patch.DigestFrequency = &v
	}
	p, err := s.prefs.Update(ctx, userID, patch)
	if err != nil {
		return nil, mapPrefsErr(err)
	}
	return preferencesToProto(p), nil
}

func preferencesToProto(p dompreferences.Preferences) *socialv1.UserPreferences {
	return &socialv1.UserPreferences{
		UserId:          p.UserID.String(),
		Locale:          p.Locale,
		PushEnabled:     p.PushEnabled,
		EmailEnabled:    p.EmailEnabled,
		DigestFrequency: p.DigestFrequency,
		UpdatedAt:       timestamppb.New(p.UpdatedAt),
	}
}

func mapPrefsErr(err error) error {
	switch {
	case errors.Is(err, dompreferences.ErrInvalidLocale),
		errors.Is(err, dompreferences.ErrInvalidDigestFrequency):
		return status.Error(codes.InvalidArgument, err.Error())
	default:
		return status.Error(codes.Internal, "internal error")
	}
}
