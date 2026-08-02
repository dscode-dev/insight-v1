// Shared httptest helpers for the adapter test suite.
//
// Each provider test spins a fake HTTP server that serves canned
// wire JSON keyed by URL path. That gives us full coverage of the
// HTTP decode + DTO unmarshal + mapper chain without ever calling
// the real provider.
package adapters_test

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

// newHTTPSrv returns a server that responds with the matching body
// for any request path whose suffix matches a key in the routes map.
// Suffix-match (rather than exact) lets the api_football client's
// query-string + URL-encoded params still hit the right handler
// (the path part is the discriminator).
func newHTTPSrv(t *testing.T, routes map[string]string) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		for prefix, body := range routes {
			if strings.HasPrefix(r.URL.Path, prefix) {
				w.Header().Set("Content-Type", "application/json")
				_, _ = w.Write([]byte(body))
				return
			}
		}
		http.Error(w, "no canned route for "+r.URL.Path, http.StatusNotFound)
	}))
}

// newHTTPSrv500 always returns 500. Used to exercise the failure
// path of the status recorder.
func newHTTPSrv500(t *testing.T) *httptest.Server {
	t.Helper()
	return httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		http.Error(w, `{"errors":{"server":"boom"}}`, http.StatusInternalServerError)
	}))
}
