package opsadmin

import (
	"context"
	"io"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"

	"github.com/google/uuid"

	appmod "github.com/konoha-labs/insight-gateway/internal/application/moderation"
	dommod "github.com/konoha-labs/insight-gateway/internal/domain/moderation"
)

type fakeRevoker struct {
	userID uuid.UUID
	count  int64
}

func (f *fakeRevoker) RevokeAllForUser(_ context.Context, id uuid.UUID) (int64, error) {
	f.userID = id
	return f.count, nil
}

type roundTripFunc func(*http.Request) (*http.Response, error)

type fakeModeration struct{ input appmod.ActInput }

func (f *fakeModeration) Act(_ context.Context, input appmod.ActInput) error {
	f.input = input
	return nil
}
func (f *fakeModeration) IsContentHidden(_ context.Context, _ dommod.TargetType, _ string) (bool, error) {
	return true, nil
}

func (fn roundTripFunc) RoundTrip(request *http.Request) (*http.Response, error) {
	return fn(request)
}

func TestContentStateUsesGatewayModerationDomain(t *testing.T) {
	id := uuid.NewString()
	moderation := &fakeModeration{}
	handler, _ := New("secret", "http://sport-hub.test", "hub-secret", &fakeRevoker{})
	handler.WithSocial(moderation, nil)
	request := httptest.NewRequest(http.MethodPost, "/social/content/post/"+id+"/hide", strings.NewReader(`{"reason":"policy"}`))
	request.SetPathValue("type", "post")
	request.SetPathValue("id", id)
	request.SetPathValue("action", "hide")
	request.Header.Set("X-Ops-Token", "secret")
	request.Header.Set("X-Operator", "operator-1")
	recorder := httptest.NewRecorder()
	handler.Require(handler.ContentState)(recorder, request)
	if recorder.Code != http.StatusOK ||
		moderation.input.Action != string(dommod.ActionRemove) ||
		moderation.input.ModeratorID != "operator-1" {
		t.Fatalf("status=%d input=%+v body=%s", recorder.Code, moderation.input, recorder.Body.String())
	}
}

func TestRequireFailsClosedAndRejectsInvalidToken(t *testing.T) {
	disabled, _ := New("", "http://sport-hub.test", "hub-secret", &fakeRevoker{})
	recorder := httptest.NewRecorder()
	disabled.Require(func(w http.ResponseWriter, _ *http.Request) {
		t.Fatal("disabled handler reached")
	})(recorder, httptest.NewRequest(http.MethodPost, "/", nil))
	if recorder.Code != http.StatusServiceUnavailable {
		t.Fatalf("status=%d", recorder.Code)
	}

	enabled, _ := New("secret", "http://sport-hub.test", "hub-secret", &fakeRevoker{})
	recorder = httptest.NewRecorder()
	enabled.Require(func(w http.ResponseWriter, _ *http.Request) {
		t.Fatal("unauthorized handler reached")
	})(recorder, httptest.NewRequest(http.MethodPost, "/", nil))
	if recorder.Code != http.StatusUnauthorized {
		t.Fatalf("status=%d", recorder.Code)
	}
}

func TestRevokeSessionsUsesCanonicalRepository(t *testing.T) {
	id := uuid.New()
	revoker := &fakeRevoker{count: 3}
	handler, _ := New("secret", "http://sport-hub.test", "hub-secret", revoker)
	request := httptest.NewRequest(http.MethodPost, "/users/"+id.String()+"/sessions/revoke", nil)
	request.SetPathValue("id", id.String())
	request.Header.Set("X-Ops-Token", "secret")
	recorder := httptest.NewRecorder()
	handler.Require(handler.RevokeSessions)(recorder, request)
	if recorder.Code != http.StatusOK || revoker.userID != id ||
		!strings.Contains(recorder.Body.String(), `"revoked_sessions":3`) {
		t.Fatalf("status=%d body=%s user=%s", recorder.Code, recorder.Body.String(), revoker.userID)
	}
}

func TestReplayDLQCallsSportHubCanonicalRoute(t *testing.T) {
	id := uuid.NewString()
	handler, _ := New("secret", "http://sport-hub.test", "hub-secret", &fakeRevoker{})
	handler.client = &http.Client{Transport: roundTripFunc(func(request *http.Request) (*http.Response, error) {
		if request.URL.Path != "/v1/dlq/"+id+"/replay" ||
			request.Header.Get("Idempotency-Key") != "operation-1" ||
			request.Header.Get("X-Ops-Token") != "hub-secret" {
			t.Fatalf("path=%s key=%s", request.URL.Path, request.Header.Get("Idempotency-Key"))
		}
		return &http.Response{
			StatusCode: http.StatusOK,
			Body:       io.NopCloser(strings.NewReader(`{"status":"replayed","dlq_id":"failure-1"}`)),
			Header:     http.Header{"Content-Type": []string{"application/json"}},
		}, nil
	})}
	request := httptest.NewRequest(http.MethodPost, "/dlq/"+id+"/replay", nil)
	request.SetPathValue("id", id)
	request.Header.Set("X-Ops-Token", "secret")
	request.Header.Set("Idempotency-Key", "operation-1")
	recorder := httptest.NewRecorder()
	handler.Require(handler.ReplayDLQ)(recorder, request)
	if recorder.Code != http.StatusOK || !strings.Contains(recorder.Body.String(), `"replayed"`) {
		t.Fatalf("status=%d body=%s", recorder.Code, recorder.Body.String())
	}
}
