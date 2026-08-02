// /v1/profile/me/bundle handler.
//
// the legacy BFF shape (today, hard-coded stub):
//
//	{
//	  "stats":    {user_id, reputation:0, posts:0, signals:0, accuracy:0.0},
//	  "badges":   [],
//	  "activity": [],
//	}
//
// Real implementation in W2.2:
//   - reputation ← Reputation.Get(user_id).score
//   - posts      ← 0 (no "discussions started" counter on User yet —
//     would need a new RPC or extending UserStats)
//   - signals    ← User.GetStats(user_id).signals_sent
//   - accuracy   ← User.GetStats(user_id).accuracy
//
// badges / activity stay empty arrays until those subsystems ship.
package social

import (
	"context"
	"net/http"

	socialv1 "github.com/konoha-labs/insight-protos/gen/go/social/v1"
	"golang.org/x/sync/errgroup"
	"google.golang.org/grpc/codes"

	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

func (h *Handlers) GetProfileBundle(w http.ResponseWriter, r *http.Request) {
	userID, ok := authmw.UserID(r.Context())
	if !ok {
		// authmw was bypassed — shouldn't happen if route is wrapped
		// correctly. Still respond cleanly so the cause is debuggable.
		writeError(w, http.StatusUnauthorized, "missing_user_id", "")
		return
	}

	ctx, cancel := context.WithTimeout(r.Context(), h.upstreamTimeout)
	defer cancel()

	// Parallel fetch: stats + reputation. Both are needed for the
	// happy-path response; either error fails the request.
	var (
		stats *socialv1.UserStats
		rep   *socialv1.Reputation
	)
	g, gctx := errgroup.WithContext(ctx)
	g.Go(func() error {
		resp, err := h.client.User.GetStats(gctx, &socialv1.GetUserStatsRequest{UserId: userID.String()})
		if err != nil {
			return err
		}
		stats = resp
		return nil
	})
	g.Go(func() error {
		resp, err := h.client.Reputation.Get(gctx, &socialv1.GetReputationRequest{UserId: userID.String()})
		if err != nil {
			return err
		}
		rep = resp
		return nil
	})
	if err := g.Wait(); err != nil {
		// NotFound on either → user doesn't exist yet (e.g. completed
		// /v1/auth/register but the social User row hasn't replicated).
		// Return the legacy BFF's zero-default shape so the Flutter screen
		// renders without crashing.
		if errIs(err, codes.NotFound) {
			writeJSON(w, r, http.StatusOK, zeroProfile(userID.String()))
			return
		}
		writeGrpcError(w, r, err)
		return
	}

	writeJSON(w, r, http.StatusOK, ProfileBundleResponse{
		Stats: ProfileStats{
			UserID:     userID.String(),
			Reputation: rep.Score,
			Posts:      0, // see package doc; needs a counter on User
			Signals:    stats.SignalsSent,
			Accuracy:   stats.Accuracy,
		},
		Badges:   []any{},
		Activity: []any{},
	})
}

// zeroProfile returns the the legacy BFF default shape — used when the
// upstream can't find a User row yet (e.g. just-registered account
// pre-replication).
func zeroProfile(userID string) ProfileBundleResponse {
	return ProfileBundleResponse{
		Stats: ProfileStats{
			UserID:     userID,
			Reputation: 0,
			Posts:      0,
			Signals:    0,
			Accuracy:   0,
		},
		Badges:   []any{},
		Activity: []any{},
	}
}
