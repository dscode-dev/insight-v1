// Package auth exposes the 4 OTP-auth endpoints as net/http handlers.
//
// Wire format MUST stay identical to the legacy BFF responses since the
// Flutter client is unchanged. See:
//   - azteca-flutter/lib/models/auth.dart  (request/response shapes)
package auth

// ---- request DTOs ----

type RequestOtpDTO struct {
	Phone string `json:"phone"`
}

type VerifyOtpDTO struct {
	Phone string `json:"phone"`
	Code  string `json:"code"`
}

type RegisterDTO struct {
	RegistrationToken string  `json:"registration_token"`
	Username          string  `json:"username"`
	DisplayName       string  `json:"display_name"`
	AccentColor       *string `json:"accent_color,omitempty"`
	// Gateway-Auth-B.1: all legal policy versions accepted at signup.
	AcceptedTermsVersion     string `json:"accepted_terms_version"`
	AcceptedPrivacyVersion   string `json:"accepted_privacy_version"`
	AcceptedUGCPolicyVersion string `json:"accepted_ugc_policy_version"`
}

type RefreshDTO struct {
	RefreshToken string `json:"refresh_token"`
}

// LogoutDTO — Auth-A Part 7/8. Revokes the presented refresh token's
// server-side session so it can no longer be refreshed.
type LogoutDTO struct {
	RefreshToken string `json:"refresh_token"`
}

type LegalAuditDTO struct {
	TermsVersion   string  `json:"terms_version"`
	PrivacyVersion string  `json:"privacy_version"`
	UGCVersion     string  `json:"ugc_version"`
	AcceptedAt     *string `json:"accepted_at"`
}

// ---- response DTOs ----

type TokenResponseDTO struct {
	AccessToken       string `json:"access_token"`
	RefreshToken      string `json:"refresh_token"`
	TokenType         string `json:"token_type"`
	AccessTTLSeconds  int    `json:"access_ttl_seconds"`
	RefreshTTLSeconds int    `json:"refresh_ttl_seconds"`
	UserID            string `json:"user_id"`
}

type RegistrationHandoffDTO struct {
	RegistrationToken      string `json:"registration_token"`
	RegistrationTTLSeconds int    `json:"registration_ttl_seconds"`
	Status                 string `json:"status"` // always "registration_required"
}

// VerifyOtpResponseDTO is a discriminated union:
//   - Status == "ok"                    → Tokens populated
//   - Status == "registration_required" → Registration populated
//
// `omitempty` on the two nested objects so JSON output matches the
// Pydantic ConfigDict(extra="forbid") shape from the legacy BFF.
type VerifyOtpResponseDTO struct {
	Status       string                  `json:"status"`
	Tokens       *TokenResponseDTO       `json:"tokens,omitempty"`
	Registration *RegistrationHandoffDTO `json:"registration,omitempty"`
}
