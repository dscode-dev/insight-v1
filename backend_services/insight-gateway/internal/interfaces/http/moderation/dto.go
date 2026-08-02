package moderation

import (
	"time"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

// ---- request DTOs ----

type CreateReportDTO struct {
	TargetType  string `json:"target_type"` // post | comment | user
	TargetID    string `json:"target_id"`
	Reason      string `json:"reason"`      // inappropriate | hate | spam | violence | other
	Description string `json:"description"` // optional
}

type ActDTO struct {
	ModeratorID string `json:"moderator_id"`
	Action      string `json:"action"` // dismiss | remove_content | restore_content | suspend_user | ban_user | restore_user
	ReportID    string `json:"report_id"`
	TargetType  string `json:"target_type"`
	TargetID    string `json:"target_id"`
	Note        string `json:"note"`
	SuspendDays int    `json:"suspend_days"`
}

// ---- response DTOs ----

type BlockDTO struct {
	TargetID string `json:"target_id"`
	Blocked  bool   `json:"blocked"`
}

type ReportDTO struct {
	ID          string    `json:"id"`
	ReporterID  string    `json:"reporter_id"`
	TargetType  string    `json:"target_type"`
	TargetID    string    `json:"target_id"`
	Reason      string    `json:"reason"`
	Description string    `json:"description,omitempty"`
	Status      string    `json:"status"`
	CreatedAt   time.Time `json:"created_at"`
	UpdatedAt   time.Time `json:"updated_at"`
}

type ReportListDTO struct {
	Reports []ReportDTO `json:"reports"`
	Total   int64       `json:"total"`
	Limit   int         `json:"limit"`
	Offset  int         `json:"offset"`
}

type ActionDTO struct {
	ID          string    `json:"id"`
	ReportID    string    `json:"report_id,omitempty"`
	ModeratorID string    `json:"moderator_id"`
	Action      string    `json:"action"`
	TargetType  string    `json:"target_type"`
	TargetID    string    `json:"target_id"`
	Note        string    `json:"note,omitempty"`
	CreatedAt   time.Time `json:"created_at"`
}

type ReasonCountDTO struct {
	Reason string `json:"reason"`
	Count  int64  `json:"count"`
}

type AggregateDTO struct {
	Key   string `json:"key"`
	Count int64  `json:"count"`
}

type StatsDTO struct {
	Open         int64            `json:"open"`
	Reviewing    int64            `json:"reviewing"`
	Resolved     int64            `json:"resolved"`
	Dismissed    int64            `json:"dismissed"`
	ByReason     []ReasonCountDTO `json:"by_reason"`
	TopPosts     []AggregateDTO   `json:"top_posts"`
	TopUsers     []AggregateDTO   `json:"top_users"`
	TopReporters []AggregateDTO   `json:"top_reporters"`
}

// ---- mapping ----

func reportDTO(r dommod.Report) ReportDTO {
	return ReportDTO{
		ID:          r.ID.String(),
		ReporterID:  r.ReporterID.String(),
		TargetType:  string(r.TargetType),
		TargetID:    r.TargetID,
		Reason:      string(r.Reason),
		Description: r.Description,
		Status:      string(r.Status),
		CreatedAt:   r.CreatedAt,
		UpdatedAt:   r.UpdatedAt,
	}
}

func actionDTO(a dommod.ActionRecord) ActionDTO {
	d := ActionDTO{
		ID:          a.ID.String(),
		ModeratorID: a.ModeratorID,
		Action:      string(a.Action),
		TargetType:  string(a.TargetType),
		TargetID:    a.TargetID,
		Note:        a.Note,
		CreatedAt:   a.CreatedAt,
	}
	if a.ReportID != nil {
		d.ReportID = a.ReportID.String()
	}
	return d
}

func statsDTO(s *appmod.Stats) StatsDTO {
	out := StatsDTO{
		Open:      s.ByStatus[dommod.StatusOpen],
		Reviewing: s.ByStatus[dommod.StatusReviewing],
		Resolved:  s.ByStatus[dommod.StatusResolved],
		Dismissed: s.ByStatus[dommod.StatusDismissed],
	}
	for _, rc := range s.ByReason {
		out.ByReason = append(out.ByReason, ReasonCountDTO{Reason: string(rc.Reason), Count: rc.Count})
	}
	for _, a := range s.TopPosts {
		out.TopPosts = append(out.TopPosts, AggregateDTO{Key: a.Key, Count: a.Count})
	}
	for _, a := range s.TopUsers {
		out.TopUsers = append(out.TopUsers, AggregateDTO{Key: a.Key, Count: a.Count})
	}
	for _, a := range s.TopReporter {
		out.TopReporters = append(out.TopReporters, AggregateDTO{Key: a.Key, Count: a.Count})
	}
	return out
}
