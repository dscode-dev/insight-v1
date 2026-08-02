package operations

import (
	"context"
	"encoding/json"
	"net/http"
	"runtime"
	"time"

	operationsv1 "github.com/konoha-labs/insight-protos/gen/go/operations/v1"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type Config struct {
	ServiceID    string
	ServiceName  string
	ServiceType  operationsv1.ServiceType
	Version      string
	Environment  string
	Tags         []string
	Capabilities []*operationsv1.Capability
	StartedAt    time.Time
	Ready        func(context.Context) error
	ActiveJobs   func(context.Context) uint64
}

type Server struct {
	operationsv1.UnimplementedOperationsServiceServer
	cfg Config
}

func New(cfg Config) *Server {
	if cfg.StartedAt.IsZero() {
		cfg.StartedAt = time.Now()
	}
	return &Server{cfg: cfg}
}

func (s *Server) Ping(ctx context.Context, req *operationsv1.PingRequest) (*operationsv1.PingResponse, error) {
	now := time.Now()
	var latency int64
	if req != nil && req.SentAt != nil {
		latency = now.Sub(req.SentAt.AsTime()).Milliseconds()
		if latency < 0 {
			latency = 0
		}
	}
	return &operationsv1.PingResponse{Identity: s.identity(), LatencyMs: latency, CheckedAt: timestamppb.New(now)}, nil
}

func (s *Server) Health(ctx context.Context, _ *operationsv1.HealthRequest) (*operationsv1.HealthResponse, error) {
	status, reason := s.status(ctx)
	return &operationsv1.HealthResponse{Identity: s.identity(), Status: status, Reason: reason, CheckedAt: timestamppb.Now()}, nil
}

func (s *Server) Status(ctx context.Context, _ *operationsv1.StatusRequest) (*operationsv1.StatusResponse, error) {
	status, reason := s.status(ctx)
	return &operationsv1.StatusResponse{
		Identity:      s.identity(),
		Status:        status,
		UptimeSeconds: uint64(time.Since(s.cfg.StartedAt).Seconds()),
		Detail:        reason,
		CheckedAt:     timestamppb.Now(),
	}, nil
}

func (s *Server) Capabilities(context.Context, *operationsv1.CapabilitiesRequest) (*operationsv1.CapabilitiesResponse, error) {
	return &operationsv1.CapabilitiesResponse{Identity: s.identity(), Capabilities: s.cfg.Capabilities, CheckedAt: timestamppb.Now()}, nil
}

func (s *Server) Metrics(ctx context.Context, _ *operationsv1.MetricsRequest) (*operationsv1.MetricsResponse, error) {
	var mem runtime.MemStats
	runtime.ReadMemStats(&mem)
	activeJobs := uint64(0)
	if s.cfg.ActiveJobs != nil {
		activeJobs = s.cfg.ActiveJobs(ctx)
	}
	return &operationsv1.MetricsResponse{
		Identity:      s.identity(),
		MemoryMb:      float64(mem.Alloc) / 1024 / 1024,
		ActiveJobs:    activeJobs,
		UptimeSeconds: uint64(time.Since(s.cfg.StartedAt).Seconds()),
		CheckedAt:     timestamppb.Now(),
		Counters: map[string]float64{
			"goroutines": float64(runtime.NumGoroutine()),
		},
	}, nil
}

func (s *Server) Routes() http.Handler {
	mux := http.NewServeMux()
	mux.HandleFunc("GET /healthz", func(w http.ResponseWriter, r *http.Request) {
		resp, _ := s.Health(r.Context(), &operationsv1.HealthRequest{})
		writeJSON(w, healthHTTPStatus(resp.Status), map[string]any{"service": s.cfg.ServiceID, "status": statusString(resp.Status)})
	})
	mux.HandleFunc("GET /status", func(w http.ResponseWriter, r *http.Request) {
		resp, _ := s.Status(r.Context(), &operationsv1.StatusRequest{})
		writeJSON(w, http.StatusOK, map[string]any{
			"service":        s.cfg.ServiceID,
			"version":        s.cfg.Version,
			"uptime_seconds": resp.UptimeSeconds,
			"status":         statusString(resp.Status),
			"checked_at":     resp.CheckedAt.AsTime().Format(time.RFC3339),
			"identity":       s.identityMap(),
		})
	})
	mux.HandleFunc("GET /capabilities", func(w http.ResponseWriter, r *http.Request) {
		caps := make([]string, 0, len(s.cfg.Capabilities))
		for _, cap := range s.cfg.Capabilities {
			if cap.Enabled {
				caps = append(caps, cap.Name)
			}
		}
		writeJSON(w, http.StatusOK, map[string]any{"service": s.cfg.ServiceID, "capabilities": caps})
	})
	mux.HandleFunc("GET /metrics/summary", func(w http.ResponseWriter, r *http.Request) {
		resp, _ := s.Metrics(r.Context(), &operationsv1.MetricsRequest{})
		writeJSON(w, http.StatusOK, map[string]any{
			"service":        s.cfg.ServiceID,
			"cpu_percent":    resp.CpuPercent,
			"memory_mb":      resp.MemoryMb,
			"active_jobs":    resp.ActiveJobs,
			"uptime_seconds": resp.UptimeSeconds,
		})
	})
	return mux
}

func (s *Server) identity() *operationsv1.ServiceIdentity {
	return &operationsv1.ServiceIdentity{
		ServiceId:   s.cfg.ServiceID,
		ServiceName: s.cfg.ServiceName,
		ServiceType: s.cfg.ServiceType,
		Version:     s.cfg.Version,
		Environment: s.cfg.Environment,
		Tags:        append([]string(nil), s.cfg.Tags...),
	}
}

func (s *Server) identityMap() map[string]any {
	id := s.identity()
	return map[string]any{
		"service_id":   id.ServiceId,
		"service_name": id.ServiceName,
		"service_type": id.ServiceType.String(),
		"version":      id.Version,
		"environment":  id.Environment,
		"tags":         id.Tags,
	}
}

func (s *Server) status(ctx context.Context) (operationsv1.OperationalStatus, string) {
	if s.cfg.Ready == nil {
		return operationsv1.OperationalStatus_OPERATIONAL_STATUS_HEALTHY, "ready"
	}
	if err := s.cfg.Ready(ctx); err != nil {
		return operationsv1.OperationalStatus_OPERATIONAL_STATUS_DEGRADED, err.Error()
	}
	return operationsv1.OperationalStatus_OPERATIONAL_STATUS_HEALTHY, "ready"
}

func statusString(status operationsv1.OperationalStatus) string {
	switch status {
	case operationsv1.OperationalStatus_OPERATIONAL_STATUS_HEALTHY:
		return "healthy"
	case operationsv1.OperationalStatus_OPERATIONAL_STATUS_DEGRADED:
		return "degraded"
	case operationsv1.OperationalStatus_OPERATIONAL_STATUS_UNHEALTHY:
		return "unhealthy"
	case operationsv1.OperationalStatus_OPERATIONAL_STATUS_UNAVAILABLE:
		return "unavailable"
	default:
		return "unknown"
	}
}

func healthHTTPStatus(status operationsv1.OperationalStatus) int {
	if status == operationsv1.OperationalStatus_OPERATIONAL_STATUS_HEALTHY {
		return http.StatusOK
	}
	return http.StatusServiceUnavailable
}

func writeJSON(w http.ResponseWriter, status int, body any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(body)
}

func Capability(name, description string) *operationsv1.Capability {
	return &operationsv1.Capability{Name: name, Version: "v1", Enabled: true, Description: description}
}
