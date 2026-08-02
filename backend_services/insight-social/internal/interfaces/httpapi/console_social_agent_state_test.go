package httpapi

import (
	"context"
	"net/http"
	"net/http/httptest"
	"testing"

	"github.com/google/uuid"
)

type noCallAgentStore struct{ called bool }

func (s *noCallAgentStore) SetActive(
	context.Context, uuid.UUID, bool, string, string, string,
) (bool, error) {
	s.called = true
	return true, nil
}

func TestAgentStateFailsClosedWithoutOpsToken(t *testing.T) {
	store := &noCallAgentStore{}
	recorder := httptest.NewRecorder()
	ConsoleSocialAgentState(store, false, "").ServeHTTP(
		recorder, httptest.NewRequest(http.MethodPost, "/console/social/agents/x/deactivate", nil),
	)
	if recorder.Code != http.StatusServiceUnavailable || store.called {
		t.Fatalf("status=%d called=%v", recorder.Code, store.called)
	}
}
