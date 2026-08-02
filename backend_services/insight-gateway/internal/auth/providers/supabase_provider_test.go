package providers

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"testing"
)

func TestSupabaseProvider_SendAndVerifyUseGoTruePhoneEndpoints(t *testing.T) {
	var seen []string
	ts := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		seen = append(seen, r.Method+" "+r.URL.Path)
		if got := r.Header.Get("apikey"); got != "anon-test-key" {
			t.Fatalf("apikey header = %q", got)
		}
		if got := r.Header.Get("Authorization"); got != "Bearer anon-test-key" {
			t.Fatalf("Authorization header = %q", got)
		}

		var body map[string]string
		if err := json.NewDecoder(r.Body).Decode(&body); err != nil {
			t.Fatalf("decode body: %v", err)
		}
		switch r.URL.Path {
		case "/auth/v1/otp":
			if body["phone"] != "+5581999999999" {
				t.Fatalf("otp phone body = %#v", body)
			}
			w.WriteHeader(http.StatusOK)
			_, _ = w.Write([]byte(`{}`))
		case "/auth/v1/verify":
			if body["phone"] != "+5581999999999" || body["token"] != "123456" || body["type"] != "sms" {
				t.Fatalf("verify body = %#v", body)
			}
			w.WriteHeader(http.StatusOK)
			// Supabase identity/session is intentionally ignored by Gateway.
			_, _ = w.Write([]byte(`{"user":{"id":"supabase-user"},"access_token":"ignored"}`))
		default:
			t.Fatalf("unexpected path %s", r.URL.Path)
		}
	}))
	defer ts.Close()

	p := NewSupabaseProvider(SupabaseConfig{
		URL:     ts.URL + "/rest/v1/",
		AnonKey: "anon-test-key",
		HTTP:    ts.Client(),
	})

	if _, err := p.SendCode(context.Background(), "+5581999999999"); err != nil {
		t.Fatalf("SendCode: %v", err)
	}
	if err := p.VerifyCode(context.Background(), "+5581999999999", "123456"); err != nil {
		t.Fatalf("VerifyCode: %v", err)
	}
	if len(seen) != 2 || seen[0] != "POST /auth/v1/otp" || seen[1] != "POST /auth/v1/verify" {
		t.Fatalf("seen requests = %#v", seen)
	}
}
