package providers

import (
	"context"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

// FirebaseProvider is a standby implementation of the Gateway-owned provider
// seam. It exists to preserve provider substitutability, but Auth-A.2 does not
// wire Firebase credentials or client SDKs. Selecting it fails closed.
type FirebaseProvider struct{}

func (FirebaseProvider) Name() string { return "firebase" }

func (FirebaseProvider) SendCode(context.Context, string) (string, error) {
	return "", domauth.ErrPhoneProviderNotConfigured
}

func (FirebaseProvider) VerifyCode(context.Context, string, string) error {
	return domauth.ErrPhoneProviderNotConfigured
}
