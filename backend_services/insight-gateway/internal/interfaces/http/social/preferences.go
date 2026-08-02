// Sprint D — preferences BFF.
//
//	GET  /v1/users/me/preferences          → PreferencesDTO
//	PUT  /v1/users/me/preferences          → PreferencesDTO (full row after patch)
//
// PUT is a partial patch: only fields present in the JSON body are
// forwarded as optional fields to social.User.UpdatePreferences.
// Missing fields are left as-is on the persisted row (the social
// repo uses COALESCE under the hood).
package social

import (
	"encoding/json"
	"net/http"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

// PreferencesDTO mirrors social.v1.UserPreferences. The locale field
// uses BCP 47 tags; valid digest_frequency values are
// "daily" | "weekly" | "never".
type PreferencesDTO struct {
	UserID          string `json:"user_id"`
	Locale          string `json:"locale"`
	PushEnabled     bool   `json:"push_enabled"`
	EmailEnabled    bool   `json:"email_enabled"`
	DigestFrequency string `json:"digest_frequency"`
	UpdatedAt       string `json:"updated_at"`
}

// PreferencesPatchRequest — all fields optional. Use pointers so we
// can distinguish "absent" (leave as-is) from "false" (explicit
// disable).
type PreferencesPatchRequest struct {
	Locale          *string `json:"locale,omitempty"`
	PushEnabled     *bool   `json:"push_enabled,omitempty"`
	EmailEnabled    *bool   `json:"email_enabled,omitempty"`
	DigestFrequency *string `json:"digest_frequency,omitempty"`
}

func (h *Handlers) GetPreferences(w http.ResponseWriter, r *http.Request) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeGrpcError(w, r, errAuthMissing)
		return
	}
	resp, err := h.client.User.GetPreferences(r.Context(), &socialv1.GetPreferencesRequest{
		UserId: userID.String(),
	})
	if err != nil {
		if errIs(err, codes.NotFound) {
			writeError(w, http.StatusNotFound, "user_not_found", "")
			return
		}
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusOK, preferencesToWire(resp))
}

func (h *Handlers) UpdatePreferences(w http.ResponseWriter, r *http.Request) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeGrpcError(w, r, errAuthMissing)
		return
	}

	var patch PreferencesPatchRequest
	if err := json.NewDecoder(http.MaxBytesReader(w, r.Body, 4<<10)).Decode(&patch); err != nil {
		writeError(w, http.StatusBadRequest, "invalid_json", err.Error())
		return
	}

	req := &socialv1.UpdatePreferencesRequest{UserId: userID.String()}
	if patch.Locale != nil {
		req.Locale = patch.Locale
	}
	if patch.PushEnabled != nil {
		req.PushEnabled = patch.PushEnabled
	}
	if patch.EmailEnabled != nil {
		req.EmailEnabled = patch.EmailEnabled
	}
	if patch.DigestFrequency != nil {
		req.DigestFrequency = patch.DigestFrequency
	}

	resp, err := h.client.User.UpdatePreferences(r.Context(), req)
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	writeJSON(w, r, http.StatusOK, preferencesToWire(resp))
}

func preferencesToWire(p *socialv1.UserPreferences) PreferencesDTO {
	return PreferencesDTO{
		UserID:          p.UserId,
		Locale:          p.Locale,
		PushEnabled:     p.PushEnabled,
		EmailEnabled:    p.EmailEnabled,
		DigestFrequency: p.DigestFrequency,
		UpdatedAt:       formatTs(p.UpdatedAt.AsTime()),
	}
}
