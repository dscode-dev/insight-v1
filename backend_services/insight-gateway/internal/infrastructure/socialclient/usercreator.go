package socialclient

import (
	"context"
	"errors"

	"github.com/google/uuid"
	"google.golang.org/grpc/codes"
	"google.golang.org/grpc/status"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
)

// UserCreator adapts social.v1.UserService to the auth domain's
// UserCreator port. The
// Social service is the source of truth for user identity.
type UserCreator struct {
	users socialv1.UserServiceClient
}

func NewUserCreator(c *Client) *UserCreator {
	return &UserCreator{users: c.User}
}

// CreateUser calls social.v1.UserService/Create. A gRPC AlreadyExists
// maps to the domain's ErrUsernameTaken sentinel so the application
// layer can errors.Is it without knowing about gRPC.
func (u *UserCreator) CreateUser(ctx context.Context, username, displayName string, accentColor *string) (uuid.UUID, error) {
	req := &socialv1.CreateUserRequest{
		Username:    username,
		DisplayName: displayName,
	}
	if accentColor != nil {
		req.AccentColor = accentColor
	}
	user, err := u.users.Create(ctx, req)
	if err != nil {
		if status.Code(err) == codes.AlreadyExists {
			return uuid.Nil, domauth.ErrUsernameTaken
		}
		return uuid.Nil, err
	}
	id, err := uuid.Parse(user.GetId())
	if err != nil {
		return uuid.Nil, errors.New("socialclient: user id is not a uuid")
	}
	return id, nil
}

// UnavailableUserCreator is wired when the social dial failed at boot:
// OTP login keeps working; registration fails with a clear error
// until social recovers and the pod restarts (or re-dials).
type UnavailableUserCreator struct{}

func (UnavailableUserCreator) CreateUser(context.Context, string, string, *string) (uuid.UUID, error) {
	return uuid.Nil, errors.New("social_user_service_unavailable")
}
