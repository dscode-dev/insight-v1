package auth

import (
	"encoding/json"
	"net/http"
	"strings"
	"time"

	"github.com/go-chi/chi/v5"
	"github.com/google/uuid"
	"github.com/rs/zerolog"

	appauth "github.com/konoha-labs/insight-gateway/internal/application/auth"
	domauth "github.com/konoha-labs/insight-gateway/internal/domain/auth"
)

// Handlers holds the chi handler funcs for the 4 OTP endpoints.
// Constructed once at boot from the application service.
type Handlers struct {
	svc   *appauth.Service
	creds domauth.CredentialRepo
}

func NewHandlers(svc *appauth.Service, creds domauth.CredentialRepo) *Handlers {
	return &Handlers{svc: svc, creds: creds}
}

// ---- POST /v1/auth/otp/request ----

func (h *Handlers) RequestOtp(w http.ResponseWriter, r *http.Request) {
	var dto RequestOtpDTO
	if err := decodeJSON(r, &dto); err != nil {
		writeBadRequest(w, "invalid_json_body")
		return
	}
	if dto.Phone == "" {
		writeBadRequest(w, "phone_required")
		return
	}

	if err := h.svc.RequestOtp(r.Context(), appauth.RequestOtpInput{
		RawPhone: dto.Phone,
	}); err != nil {
		logHandlerError(r, "request_otp", err)
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusAccepted)
}

// ---- POST /v1/auth/otp/verify ----

func (h *Handlers) VerifyOtp(w http.ResponseWriter, r *http.Request) {
	var dto VerifyOtpDTO
	if err := decodeJSON(r, &dto); err != nil {
		writeBadRequest(w, "invalid_json_body")
		return
	}
	if dto.Phone == "" || dto.Code == "" {
		writeBadRequest(w, "phone_and_code_required")
		return
	}

	result, err := h.svc.VerifyOtp(r.Context(), appauth.VerifyOtpInput{
		RawPhone: dto.Phone,
		Code:     dto.Code,
	})
	if err != nil {
		logHandlerError(r, "verify_otp", err)
		writeError(w, err)
		return
	}
	writeVerifyResult(w, result)
}

// writeVerifyResult serializes the shared phone-verified union (login tokens
// or registration handoff). Keeping ONE writer mirrors the single resolvePhone
// branch in the service, so provider choice never changes the response shape.
func writeVerifyResult(w http.ResponseWriter, result *appauth.VerifyOtpResult) {
	resp := VerifyOtpResponseDTO{}
	switch {
	case result.Tokens != nil:
		resp.Status = "ok"
		resp.Tokens = tokensToDTO(result.Tokens)
	case result.Registration != nil:
		resp.Status = "registration_required"
		resp.Registration = &RegistrationHandoffDTO{
			RegistrationToken:      result.Registration.RegistrationToken,
			RegistrationTTLSeconds: result.Registration.RegistrationTTLSeconds,
			Status:                 "registration_required",
		}
	default:
		// Defensive — the service should always populate one branch.
		writeError(w, errInternalUnreachable)
		return
	}
	writeJSON(w, http.StatusOK, resp)
}

// ---- POST /v1/auth/register ----

func (h *Handlers) Register(w http.ResponseWriter, r *http.Request) {
	var dto RegisterDTO
	if err := decodeJSON(r, &dto); err != nil {
		writeBadRequest(w, "invalid_json_body")
		return
	}
	if dto.RegistrationToken == "" || dto.Username == "" || dto.DisplayName == "" {
		writeBadRequest(w, "registration_fields_required")
		return
	}
	if strings.TrimSpace(dto.AcceptedTermsVersion) == "" ||
		strings.TrimSpace(dto.AcceptedPrivacyVersion) == "" ||
		strings.TrimSpace(dto.AcceptedUGCPolicyVersion) == "" {
		writeBadRequest(w, "legal_acceptance_required")
		return
	}

	tokens, err := h.svc.CompleteRegistration(r.Context(), appauth.CompleteRegistrationInput{
		RegistrationToken:        dto.RegistrationToken,
		Username:                 dto.Username,
		DisplayName:              dto.DisplayName,
		AccentColor:              dto.AccentColor,
		AcceptedTermsVersion:     dto.AcceptedTermsVersion,
		AcceptedPrivacyVersion:   dto.AcceptedPrivacyVersion,
		AcceptedUGCPolicyVersion: dto.AcceptedUGCPolicyVersion,
	})
	if err != nil {
		logHandlerError(r, "register", err)
		writeError(w, err)
		return
	}

	writeJSON(w, http.StatusCreated, tokensToDTO(tokens))
}

// ---- POST /v1/auth/refresh ----

func (h *Handlers) Refresh(w http.ResponseWriter, r *http.Request) {
	var dto RefreshDTO
	if err := decodeJSON(r, &dto); err != nil {
		writeBadRequest(w, "invalid_json_body")
		return
	}
	if dto.RefreshToken == "" {
		writeBadRequest(w, "refresh_token_required")
		return
	}

	tokens, err := h.svc.Refresh(r.Context(), appauth.RefreshInput{
		RefreshToken: dto.RefreshToken,
	})
	if err != nil {
		logHandlerError(r, "refresh", err)
		writeError(w, err)
		return
	}

	writeJSON(w, http.StatusOK, tokensToDTO(tokens))
}

// ---- POST /v1/auth/logout (Auth-A Part 7/8) ----

func (h *Handlers) Logout(w http.ResponseWriter, r *http.Request) {
	var dto LogoutDTO
	if err := decodeJSON(r, &dto); err != nil {
		writeBadRequest(w, "invalid_json_body")
		return
	}
	if dto.RefreshToken == "" {
		writeBadRequest(w, "refresh_token_required")
		return
	}

	// Idempotent: revoking an unknown/already-revoked token is a 204 too, so
	// the client can always treat logout as "succeeded".
	if err := h.svc.Logout(r.Context(), dto.RefreshToken); err != nil {
		logHandlerError(r, "logout", err)
		writeError(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- GET /v1/admin/users/{id}/legal ----

func (h *Handlers) UserLegalAudit(w http.ResponseWriter, r *http.Request) {
	if h.creds == nil {
		writeError(w, errInternalUnreachable)
		return
	}
	rawID := chi.URLParam(r, "id")
	userID, err := uuid.Parse(rawID)
	if err != nil {
		writeBadRequest(w, "invalid_user_id")
		return
	}
	cred, err := h.creds.GetByUserID(r.Context(), userID)
	if err != nil {
		logHandlerError(r, "admin_user_legal", err)
		writeError(w, err)
		return
	}
	var acceptedAt *string
	if cred.AcceptedLegalAt != nil {
		formatted := cred.AcceptedLegalAt.UTC().Format(time.RFC3339)
		acceptedAt = &formatted
	}
	writeJSON(w, http.StatusOK, LegalAuditDTO{
		TermsVersion:   cred.AcceptedTermsVersion,
		PrivacyVersion: cred.AcceptedPrivacyVersion,
		UGCVersion:     cred.AcceptedUGCPolicyVersion,
		AcceptedAt:     acceptedAt,
	})
}

// ---- helpers ----

func decodeJSON(r *http.Request, dst any) error {
	dec := json.NewDecoder(r.Body)
	dec.DisallowUnknownFields()
	return dec.Decode(dst)
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeBadRequest(w http.ResponseWriter, detail string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusBadRequest)
	_ = json.NewEncoder(w).Encode(map[string]string{"detail": detail})
}

func tokensToDTO(t *appauth.IssuedTokens) *TokenResponseDTO {
	return &TokenResponseDTO{
		AccessToken:       t.AccessToken,
		RefreshToken:      t.RefreshToken,
		TokenType:         "Bearer",
		AccessTTLSeconds:  t.AccessTTLSeconds,
		RefreshTTLSeconds: t.RefreshTTLSeconds,
		UserID:            t.UserID.String(),
	}
}

func logHandlerError(r *http.Request, endpoint string, err error) {
	zerolog.Ctx(r.Context()).Warn().
		Err(err).
		Str("endpoint", endpoint).
		Msg("auth_handler_error")
}

// errInternalUnreachable — sentinel for the "shouldn't happen" branch
// in VerifyOtp where the service returned a result with neither
// branch populated. Mapped to 500 via mapError.
type stringErr string

func (e stringErr) Error() string { return string(e) }

const errInternalUnreachable stringErr = "unreachable_branch"
