// Package observability — Sprint 3 (Social Foundation) Prometheus
// counters. Registered on the default registry, which the runtime-go
// metrics handler already serves on /metrics.
package observability

import (
	"github.com/prometheus/client_golang/prometheus"
	"github.com/prometheus/client_golang/prometheus/promauto"
)

var (
	PostsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "social_posts_total",
		Help: "Posts created, by author type.",
	}, []string{"author_type"})

	AgentPostsTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "social_agent_posts_total",
		Help: "Posts created by platform agents.",
	})

	// CONSOLE-SOCIAL-B: publications blocked because the agent is deactivated —
	// proves agent operational enforcement is real (non-decorative).
	AgentPublishBlockedTotal = promauto.NewCounter(prometheus.CounterOpts{
		Name: "social_agent_publish_blocked_total",
		Help: "Agent post publications rejected because the agent is deactivated.",
	})

	CommentsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "social_comments_total",
		Help: "Comments created, by depth (1 = comment, 2 = reply).",
	}, []string{"depth"})

	FollowsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "social_follows_total",
		Help: "Follow edges created, by origin (api / auto_agent).",
	}, []string{"origin"})

	FeedReadsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "social_feed_reads_total",
		Help: "Feed reads served, by feed kind (global / following).",
	}, []string{"feed"})

	ReactionsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "social_reactions_total",
		Help: "Post reactions, by action (like / unlike).",
	}, []string{"action"})

	MutedRelationshipsTotal = promauto.NewCounterVec(prometheus.CounterOpts{
		Name: "social_muted_relationships_total",
		Help: "Mute toggles on follow edges, by action (mute / unmute).",
	}, []string{"action"})
)
