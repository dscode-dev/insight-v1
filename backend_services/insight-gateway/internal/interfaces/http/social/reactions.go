// Sprint B — Reaction BFF endpoints.
//
//	POST   /v1/reactions/discussion/{discussion_id}  → 201 + Reaction
//	DELETE /v1/reactions/discussion/{discussion_id}  → 204
//
// Author/viewer is ALWAYS taken from the JWT (authmw). Request body
// is empty for both routes — only the (path id, viewer from token,
// implicit kind=LIKE) triple matters.
//
// Idempotency: React is idempotent server-side (CTE INSERT
// ON CONFLICT DO NOTHING + return-existing-row); Unreact returns 204
// whether or not the row existed. Clients can retry both safely.
package social

import (
	"context"
	"net/http"

	"github.com/go-chi/chi/v5"
	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"google.golang.org/grpc/codes"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

func (h *Handlers) ReactToDiscussion(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "discussion_id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "missing_discussion_id", "")
		return
	}
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeGrpcError(w, r, errAuthMissing)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	rec, err := h.client.Reaction.React(ctx, &socialv1.ReactRequest{
		UserId:       userID.String(),
		DiscussionId: id,
		Kind:         socialv1.ReactionKind_REACTION_KIND_LIKE,
	})
	if err != nil {
		if errIs(err, codes.NotFound) {
			writeError(w, http.StatusNotFound, "discussion_not_found", "")
			return
		}
		writeGrpcError(w, r, err)
		return
	}

	writeJSON(w, r, http.StatusCreated, ReactionDTO{
		UserID:       rec.UserId,
		DiscussionID: rec.DiscussionId,
		Kind:         "like",
		CreatedAt:    formatTs(rec.CreatedAt.AsTime()),
	})
}

func (h *Handlers) UnreactToDiscussion(w http.ResponseWriter, r *http.Request) {
	id := chi.URLParam(r, "discussion_id")
	if id == "" {
		writeError(w, http.StatusBadRequest, "missing_discussion_id", "")
		return
	}
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		writeGrpcError(w, r, errAuthMissing)
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	_, err := h.client.Reaction.Unreact(ctx, &socialv1.UnreactRequest{
		UserId:       userID.String(),
		DiscussionId: id,
		Kind:         socialv1.ReactionKind_REACTION_KIND_LIKE,
	})
	if err != nil {
		writeGrpcError(w, r, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}
