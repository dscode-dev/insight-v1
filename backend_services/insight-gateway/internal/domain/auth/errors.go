// Package auth holds the WhatsApp-style OTP domain.
//
// Entities:
//   - Credential        — the durable identity row keyed by phone_e164,
//     linked to a Social user_id + username.
//   - OtpChallenge      — short-lived (10 min) row issued by request_otp
//     and consumed by verify_otp.
//
// Domain errors are sentinel values defined here. Application layer
// translates them to HTTP status via interfaces/http/auth/errors.go.
//
// Hexagonal note: this package has zero imports from anywhere outside
// the standard library. Ports (repositories, SMS provider, JWT codec,
// user creator) are interfaces declared here; implementations live in
// internal/infrastructure/*.
package auth

import "errors"

// Sentinel errors. The HTTP layer pattern-matches on these via
// errors.Is to choose status codes. Adding a new error requires
// adding the corresponding status mapping in interfaces/http/auth.
var (
	// ErrInvalidPhone — input couldn't be normalized to E.164, or was
	// rejected as non-mobile.
	ErrInvalidPhone = errors.New("invalid_phone")

	// ErrOtpResendCooldown — too soon after the last request for this
	// phone. Maps to HTTP 429.
	ErrOtpResendCooldown = errors.New("otp_resend_cooldown")

	// ErrOtpDispatch — SMS provider rejected the send. Maps to HTTP 503
	// (service-side problem, not user-fixable).
	ErrOtpDispatch = errors.New("otp_dispatch_failed")

	// ErrOtpInvalid — wrong code OR no live challenge for this phone.
	// We deliberately don't distinguish the two so user enumeration
	// is impossible. Maps to HTTP 401.
	ErrOtpInvalid = errors.New("otp_invalid_or_expired")

	// ErrOtpExpired — live challenge exists but expires_at has passed.
	// Surfaced separately so the UI can prompt for a resend.
	// Maps to HTTP 410.
	ErrOtpExpired = errors.New("otp_expired")

	// ErrOtpExhausted — max attempts hit on the freshest challenge.
	// Maps to HTTP 429.
	ErrOtpExhausted = errors.New("otp_max_attempts")

	// ErrInvalidRegistrationToken — JWT carrying the verified phone
	// failed to decode, expired, or has the wrong typ claim.
	ErrInvalidRegistrationToken = errors.New("invalid_registration_token")

	// ErrUsernameTaken — register attempted with a username already
	// owned by a credential row. Maps to HTTP 409.
	ErrUsernameTaken = errors.New("username_taken")

	// ErrTermsNotAccepted — registration without accepting the current Terms
	// of Use / Privacy Policy version (Store-A, App Store / Play requirement).
	// Maps to HTTP 400.
	ErrTermsNotAccepted = errors.New("terms_not_accepted")

	// ErrInvalidCredentials — refresh-token decode/verify failed.
	// Maps to HTTP 401.
	ErrInvalidCredentials = errors.New("invalid_credentials")

	// ErrUserNotFound — refresh-token decoded but the linked
	// credential row no longer exists. Maps to HTTP 401.
	ErrUserNotFound = errors.New("user_not_found")

	// ErrPhoneProviderNotConfigured — AUTH_PROVIDER selected an upstream
	// provider but its required env vars are missing. Maps to HTTP 503.
	ErrPhoneProviderNotConfigured = errors.New("phone_provider_not_configured")

	// ErrPhoneProviderInvalid — upstream rejected the OTP verification. We do
	// not expose upstream identity/user details. Maps to HTTP 401.
	ErrPhoneProviderInvalid = errors.New("phone_provider_invalid")

	// ErrRefreshNotFound — the presented refresh token has no server-side
	// session row (never issued by us, or pruned). Maps to HTTP 401. (Part 7)
	ErrRefreshNotFound = errors.New("refresh_session_not_found")

	// ErrRefreshRevoked — the refresh token's session was revoked (logout,
	// rotation, or reuse-after-rotation) or has expired server-side.
	// Maps to HTTP 401. (Part 7)
	ErrRefreshRevoked = errors.New("refresh_session_revoked")
)
