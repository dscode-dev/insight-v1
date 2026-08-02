package auth

import (
	"encoding/json"
	"errors"
	"net/http"

	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

// writeError maps a domain error to an HTTP status + JSON body.
// Body shape mirrors FastAPI's default { "detail": "<message>" } so
// the Flutter client's existing error handler is unchanged.
//
// Unknown errors map to 500 with a generic message — the underlying
// error is logged at the handler entry point, never echoed back.
func writeError(w http.ResponseWriter, err error) {
	status, detail := mapError(err)
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}

func mapError(err error) (int, string) {
	switch {
	case errors.Is(err, domauth.ErrInvalidPhone):
		return http.StatusBadRequest, "invalid_phone"
	case errors.Is(err, domauth.ErrOtpResendCooldown):
		return http.StatusTooManyRequests, "otp_resend_cooldown"
	case errors.Is(err, domauth.ErrOtpDispatch):
		return http.StatusServiceUnavailable, "sms_dispatch_failed"
	case errors.Is(err, domauth.ErrOtpInvalid):
		return http.StatusUnauthorized, "otp_invalid_or_expired"
	case errors.Is(err, domauth.ErrOtpExpired):
		return http.StatusGone, "otp_expired"
	case errors.Is(err, domauth.ErrOtpExhausted):
		return http.StatusTooManyRequests, "otp_max_attempts"
	case errors.Is(err, domauth.ErrInvalidRegistrationToken):
		return http.StatusUnauthorized, "invalid_registration_token"
	case errors.Is(err, domauth.ErrUsernameTaken):
		return http.StatusConflict, "username_taken"
	case errors.Is(err, domauth.ErrTermsNotAccepted):
		return http.StatusBadRequest, "terms_not_accepted"
	case errors.Is(err, domauth.ErrInvalidCredentials):
		return http.StatusUnauthorized, "invalid_credentials"
	case errors.Is(err, domauth.ErrUserNotFound):
		return http.StatusUnauthorized, "user_not_found"
	case errors.Is(err, domauth.ErrCredentialNotFound):
		return http.StatusNotFound, "user_not_found"
	case errors.Is(err, domauth.ErrPhoneProviderNotConfigured):
		return http.StatusServiceUnavailable, "phone_provider_not_configured"
	case errors.Is(err, domauth.ErrPhoneProviderInvalid):
		return http.StatusUnauthorized, "otp_invalid_or_expired"
	case errors.Is(err, domauth.ErrRefreshNotFound):
		return http.StatusUnauthorized, "invalid_credentials"
	case errors.Is(err, domauth.ErrRefreshRevoked):
		return http.StatusUnauthorized, "refresh_revoked"
	default:
		return http.StatusInternalServerError, "internal_error"
	}
}
