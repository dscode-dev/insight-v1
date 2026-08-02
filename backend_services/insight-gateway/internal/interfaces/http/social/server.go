// Server (Handlers) — composition root for the 4 social BFF endpoints.
//
// One Handlers struct holds the gRPC clients + per-request budgets.
// Each handler method is a thin orchestration over the clients +
// JSON shaping; no business logic lives in interfaces/http/social/.
package social

import (
	"time"

	"github.com/konoha-labs/insight-gateway/internal/infrastructure/socialclient"
)

const (
	// Conservative defaults — the legacy BFF used 10s for upstream calls;
	// we go a hair tighter because the gRPC path is lower-latency than
	// the legacy HTTP path it replaced.
	defaultUpstreamTimeout = 6 * time.Second

	// BFF aggregation caps — match the legacy BFF limits.
	feedCommunityFanout         = 20
	feedDiscussionsPerCommunity = 5
	feedItemsCap                = 50

	hubCommunitiesCap = 20
	hubDiscussionsCap = 20

	communityDiscussionsCap = 20
)

type Handlers struct {
	client          *socialclient.Client
	upstreamTimeout time.Duration
}

// Deps is the minimal struct main.go passes in. Keeping it explicit
// makes test wiring (with a fake client) one line.
type Deps struct {
	Client          *socialclient.Client
	UpstreamTimeout time.Duration // optional; defaults to 6s
}

func NewHandlers(d Deps) *Handlers {
	t := d.UpstreamTimeout
	if t <= 0 {
		t = defaultUpstreamTimeout
	}
	return &Handlers{client: d.Client, upstreamTimeout: t}
}
