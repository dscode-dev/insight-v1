package anvilproxy

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/go-chi/chi/v5"
)

func TestMatchFeaturesProxiesAuthenticatedRequest(t *testing.T) {
	upstream := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get(anvilKeyHeader) != "internal-key" {
			t.Fatalf("missing internal key")
		}
		if !strings.Contains(r.URL.Path, "/internal/features/matches/m1") {
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
		w.Header().Set("Content-Type", "application/json")
		_, _ = w.Write([]byte(`{"minute":72}`))
	}))
	defer upstream.Close()

	h, err := New(Config{
		AtlasAPIKey: "atlas-key",
		AnvilURL:    upstream.URL,
		AnvilAPIKey: "internal-key",
	})
	if err != nil {
		t.Fatal(err)
	}
	router := chi.NewRouter()
	router.Get("/v1/internal/anvil/features/matches/{match_id}", h.MatchFeatures)
	req := httptest.NewRequest(
		http.MethodGet,
		"/v1/internal/anvil/features/matches/m1?series_limit=6",
		nil,
	)
	req.Header.Set(atlasKeyHeader, "atlas-key")
	rec := httptest.NewRecorder()
	router.ServeHTTP(rec, req)
	if rec.Code != http.StatusOK || !strings.Contains(rec.Body.String(), `"minute":72`) {
		t.Fatalf("status=%d body=%s", rec.Code, rec.Body.String())
	}
}

func TestMatchFeaturesRejectsInvalidKey(t *testing.T) {
	h, err := New(Config{
		AtlasAPIKey: "atlas-key",
		AnvilURL:    "http://anvil.test",
		AnvilAPIKey: "internal-key",
	})
	if err != nil {
		t.Fatal(err)
	}
	router := chi.NewRouter()
	router.Get("/v1/internal/anvil/features/matches/{match_id}", h.MatchFeatures)
	rec := httptest.NewRecorder()
	router.ServeHTTP(
		rec,
		httptest.NewRequest(
			http.MethodGet,
			"/v1/internal/anvil/features/matches/m1",
			nil,
		),
	)
	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d", rec.Code)
	}
}
