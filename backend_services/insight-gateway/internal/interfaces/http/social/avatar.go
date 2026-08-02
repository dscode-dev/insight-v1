// Sprint C — Avatar upload BFF.
//
//	POST /v1/users/me/avatar  multipart/form-data: file=<image bytes>
//	                          → 200 + ProfileAvatarResponse
//
// Flow:
//  1. authmw → user_id.
//  2. Parse multipart, detect content type, cap size.
//  3. avatarstore.Put → public URL.
//  4. social.User.UpdateAvatar(user_id, url) → persists pointer.
//  5. Respond with the URL so the client refreshes its in-memory state.
//
// The body parsing uses http.MaxBytesReader to enforce the upper
// bound BEFORE the multipart parser allocates buffers — protects
// against a client sending a huge file.
package social

import (
	"context"
	"net/http"
	"strings"
	"time"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	rtmiddleware "github.com/konoha-labs/insight-runtime-go/pkg/middleware"
	"github.com/rs/zerolog"

	"github.com/konoha-labs/insight-gateway/internal/infrastructure/avatarstore"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

// AvatarHandlers is composed alongside Handlers in main.go because
// it needs an additional dependency (avatarstore.Store) the base
// Handlers struct doesn't carry.
type AvatarHandlers struct {
	socialClient socialClient
	store        *avatarstore.Store
	maxBytes     int64
}

// socialClient narrows the dependency to just what the avatar endpoint
// needs — keeps tests easy + signals intent.
type socialClient interface {
	UpdateUserAvatar(ctx context.Context, req *socialv1.UpdateAvatarRequest) (*socialv1.User, error)
}

// NewAvatarHandlers — wired by main.go after socialclient + avatarstore
// are both up. Pass the real *socialclient.Client wrapped in a small
// adapter declared next to main (or in this file).
func NewAvatarHandlers(client socialClient, store *avatarstore.Store, maxBytes int64) *AvatarHandlers {
	if maxBytes <= 0 {
		maxBytes = 5 << 20
	}
	return &AvatarHandlers{
		socialClient: client,
		store:        store,
		maxBytes:     maxBytes,
	}
}

// ProfileAvatarResponse — what the client refreshes its state from
// after a successful upload.
type ProfileAvatarResponse struct {
	AvatarURL string `json:"avatar_url"`
}

func (h *AvatarHandlers) UploadAvatar(w http.ResponseWriter, r *http.Request) {
	started := time.Now()
	requestID := rtmiddleware.RequestIDFromContext(r.Context())
	logger := zerolog.Ctx(r.Context()).With().
		Str("request_id", requestID).
		Logger()

	userID, ok := authmw.UserID(r.Context())
	if !ok {
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "not_attempted").
			Str("failure_reason", "auth_missing").
			Msg("avatar.upload.failed")
		writeGrpcError(w, r, errAuthMissing)
		return
	}
	logger.Info().
		Str("storage_result", "not_attempted").
		Msg("avatar.upload.started")

	// Enforce body cap before the multipart parser allocates.
	r.Body = http.MaxBytesReader(w, r.Body, h.maxBytes)

	// 32 MiB in-memory limit for the multipart parser — anything
	// beyond that spools to disk. Our overall cap is 5 MiB so this
	// is effectively the upper bound.
	if err := r.ParseMultipartForm(h.maxBytes); err != nil {
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "not_attempted").
			Str("failure_reason", "multipart_parse_failed").
			Msg("avatar.upload.failed")
		writeError(w, http.StatusRequestEntityTooLarge, "payload_too_large", err.Error())
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "not_attempted").
			Str("failure_reason", "missing_file").
			Msg("avatar.upload.failed")
		writeError(w, http.StatusBadRequest, "missing_file", err.Error())
		return
	}
	defer func() { _ = file.Close() }()

	contentType := header.Header.Get("Content-Type")
	contentType = strings.SplitN(contentType, ";", 2)[0] // strip charset etc.
	if !isAllowedImageType(contentType) {
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "not_attempted").
			Str("failure_reason", "unsupported_media_type").
			Msg("avatar.upload.failed")
		writeError(w, http.StatusUnsupportedMediaType, "unsupported_media_type", contentType)
		return
	}
	if header.Size > h.maxBytes {
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "not_attempted").
			Str("failure_reason", "payload_too_large").
			Msg("avatar.upload.failed")
		writeError(w, http.StatusRequestEntityTooLarge, "payload_too_large", "")
		return
	}

	// 1. Upload to object store.
	publicURL, err := h.store.Put(r.Context(), userID, contentType, file, header.Size)
	if err != nil {
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "failed").
			Str("failure_reason", "storage_put_failed").
			Msg("avatar.upload.failed")
		writeError(w, http.StatusBadGateway, "upload_failed", err.Error())
		return
	}

	// 2. Persist the URL pointer on the user row via gRPC.
	if _, err := h.socialClient.UpdateUserAvatar(r.Context(), &socialv1.UpdateAvatarRequest{
		Id:        userID.String(),
		AvatarUrl: publicURL,
	}); err != nil {
		// Object exists in storage but persistence failed. Don't
		// roll back the upload — the next successful UpdateAvatar
		// overwrites at the same key. Surface the error so the
		// client can retry.
		logger.Warn().
			Dur("duration", time.Since(started)).
			Str("storage_result", "stored").
			Str("failure_reason", "profile_persist_failed").
			Msg("avatar.upload.failed")
		writeGrpcError(w, r, err)
		return
	}

	logger.Info().
		Dur("duration", time.Since(started)).
		Str("storage_result", "stored").
		Msg("avatar.upload.success")
	writeJSON(w, r, http.StatusOK, ProfileAvatarResponse{AvatarURL: publicURL})
}

func isAllowedImageType(ct string) bool {
	switch ct {
	case "image/jpeg", "image/png", "image/webp":
		return true
	default:
		return false
	}
}
