// Package moderation exposes the Gateway's UGC-safety HTTP surface (Store-A):
//
//	user-facing (Bearer auth):
//	  POST   /v1/users/{id}/block      DELETE /v1/users/{id}/block
//	  POST   /v1/reports
//	admin (X-Console-Service-Token, Console only):
//	  GET    /v1/admin/moderation/reports
//	  GET    /v1/admin/moderation/stats
//	  GET    /v1/admin/moderation/actions
//	  POST   /v1/admin/moderation/actions
package moderation

import (
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"strconv"

	"github.com/go-chi/chi/v5"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
	"github.com/konoha-labs/insight-gateway/internal/interfaces/http/authmw"
)

type Handlers struct {
	svc *appmod.Service
}

func NewHandlers(svc *appmod.Service) *Handlers {
	return &Handlers{svc: svc}
}

const maxBodyBytes = 16 << 10

// ---- user-facing ----

func (h *Handlers) Block(w http.ResponseWriter, r *http.Request) {
	uid, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	target := chi.URLParam(r, "id")
	if err := h.svc.Block(r.Context(), uid, target); err != nil {
		writeMod(w, err)
		return
	}
	writeJSON(w, http.StatusOK, BlockDTO{TargetID: target, Blocked: true})
}

func (h *Handlers) Unblock(w http.ResponseWriter, r *http.Request) {
	uid, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	target := chi.URLParam(r, "id")
	if err := h.svc.Unblock(r.Context(), uid, target); err != nil {
		writeMod(w, err)
		return
	}
	writeJSON(w, http.StatusOK, BlockDTO{TargetID: target, Blocked: false})
}

func (h *Handlers) CreateReport(w http.ResponseWriter, r *http.Request) {
	uid, ok := authmw.UserID(r.Context())
	if !ok {
		writeErr(w, http.StatusUnauthorized, "unauthorized")
		return
	}
	var body CreateReportDTO
	if !decode(w, r, &body) {
		return
	}
	rep, err := h.svc.Report(r.Context(), appmod.ReportInput{
		ReporterID:  uid,
		TargetType:  body.TargetType,
		TargetID:    body.TargetID,
		Reason:      body.Reason,
		Description: body.Description,
	})
	if err != nil {
		writeMod(w, err)
		return
	}
	writeJSON(w, http.StatusCreated, reportDTO(*rep))
}

// ---- admin (Console) ----

func (h *Handlers) ListReports(w http.ResponseWriter, r *http.Request) {
	q := r.URL.Query()
	f := dommod.ReportFilter{Limit: atoiDefault(q.Get("limit"), 50), Offset: atoiDefault(q.Get("offset"), 0)}
	if v := q.Get("status"); v != "" {
		s := dommod.Status(v)
		f.Status = &s
	}
	if v := q.Get("reason"); v != "" {
		rs := dommod.Reason(v)
		f.Reason = &rs
	}
	if v := q.Get("target_type"); v != "" {
		tt := dommod.TargetType(v)
		f.TargetType = &tt
	}
	if v := q.Get("target_id"); v != "" {
		f.TargetID = &v
	}
	if v := q.Get("reporter_id"); v != "" {
		f.ReporterID = &v
	}
	reports, total, err := h.svc.ListReports(r.Context(), f)
	if err != nil {
		writeMod(w, err)
		return
	}
	out := make([]ReportDTO, 0, len(reports))
	for _, rep := range reports {
		out = append(out, reportDTO(rep))
	}
	writeJSON(w, http.StatusOK, ReportListDTO{Reports: out, Total: total, Limit: f.Limit, Offset: f.Offset})
}

func (h *Handlers) Stats(w http.ResponseWriter, r *http.Request) {
	stats, err := h.svc.Stats(r.Context())
	if err != nil {
		writeMod(w, err)
		return
	}
	writeJSON(w, http.StatusOK, statsDTO(stats))
}

func (h *Handlers) ListActions(w http.ResponseWriter, r *http.Request) {
	limit := atoiDefault(r.URL.Query().Get("limit"), 50)
	actions, err := h.svc.ListActions(r.Context(), limit)
	if err != nil {
		writeMod(w, err)
		return
	}
	out := make([]ActionDTO, 0, len(actions))
	for _, a := range actions {
		out = append(out, actionDTO(a))
	}
	writeJSON(w, http.StatusOK, map[string]any{"actions": out})
}

func (h *Handlers) Act(w http.ResponseWriter, r *http.Request) {
	var body ActDTO
	if !decode(w, r, &body) {
		return
	}
	if body.ModeratorID == "" {
		writeErr(w, http.StatusBadRequest, "moderator_id_required")
		return
	}
	if err := h.svc.Act(r.Context(), appmod.ActInput{
		ModeratorID: body.ModeratorID,
		Action:      body.Action,
		ReportID:    body.ReportID,
		TargetType:  body.TargetType,
		TargetID:    body.TargetID,
		Note:        body.Note,
		SuspendDays: body.SuspendDays,
	}); err != nil {
		writeMod(w, err)
		return
	}
	w.WriteHeader(http.StatusNoContent)
}

// ---- helpers ----

func decode(w http.ResponseWriter, r *http.Request, into any) bool {
	defer func() { _, _ = io.Copy(io.Discard, r.Body) }()
	dec := json.NewDecoder(io.LimitReader(r.Body, maxBodyBytes))
	if err := dec.Decode(into); err != nil {
		writeErr(w, http.StatusBadRequest, "invalid_json")
		return false
	}
	return true
}

func atoiDefault(s string, def int) int {
	if s == "" {
		return def
	}
	if v, err := strconv.Atoi(s); err == nil {
		return v
	}
	return def
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json; charset=utf-8")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func writeErr(w http.ResponseWriter, status int, code string) {
	writeJSON(w, status, map[string]string{"detail": code})
}

func writeMod(w http.ResponseWriter, err error) {
	switch {
	case errors.Is(err, dommod.ErrSelfBlock):
		writeErr(w, http.StatusBadRequest, "cannot_block_self")
	case errors.Is(err, dommod.ErrInvalidTarget):
		writeErr(w, http.StatusBadRequest, "invalid_target")
	case errors.Is(err, dommod.ErrInvalidReason):
		writeErr(w, http.StatusBadRequest, "invalid_reason")
	case errors.Is(err, dommod.ErrInvalidAction):
		writeErr(w, http.StatusBadRequest, "invalid_action")
	case errors.Is(err, dommod.ErrReportNotFound):
		writeErr(w, http.StatusNotFound, "report_not_found")
	default:
		writeErr(w, http.StatusInternalServerError, "internal_error")
	}
}
