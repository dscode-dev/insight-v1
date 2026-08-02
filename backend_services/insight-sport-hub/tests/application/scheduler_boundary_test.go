// Sprint 3 boundary tests — extra assertions on top of the
// generic internal-package boundary walker.
//
// Locks in the architectural rules the Sprint 3 spec called out
// verbatim:
//
//	"scheduler never imports provider implementations directly"
//	"job queue can later be swapped for Redis without touching
//	 business logic"
//	"adapters never know polling intervals"
//	"adapters never know quotas"
//
// The first two are import-graph rules — parsed below. The latter
// two are static rules: provider packages must NOT mention
// syncdom.PollPolicy / syncdom.RateLimitPolicy outside Identity()
// hand-off types. We assert via grep — cheap, deterministic.
package application_test

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// internalSubtreeImports returns every distinct imported package path
// across every non-test .go file under `root`.
func internalSubtreeImports(t *testing.T, root string) []string {
	t.Helper()
	fset := token.NewFileSet()
	seen := map[string]struct{}{}
	err := filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		if !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		ast, perr := parser.ParseFile(fset, p, nil, parser.ImportsOnly)
		if perr != nil {
			return perr
		}
		for _, imp := range ast.Imports {
			seen[strings.Trim(imp.Path.Value, `"`)] = struct{}{}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk %s: %v", root, err)
	}
	out := make([]string, 0, len(seen))
	for p := range seen {
		out = append(out, p)
	}
	return out
}

func TestSchedulerDoesNotImportConcreteAdapters(t *testing.T) {
	imports := internalSubtreeImports(t, "../../internal/application/scheduler")
	for _, p := range imports {
		if strings.HasPrefix(p, "github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/") {
			t.Errorf("scheduler imports concrete provider adapter %q — must go through ports.SourceAdapter", p)
		}
		if strings.HasPrefix(p, "github.com/konoha-labs/insight-sports-hub/internal/adapters/queue") {
			t.Errorf("scheduler imports concrete queue adapter %q — must go through ports.JobQueue", p)
		}
		// Sprint 4: Redis client must be invisible to the application layer.
		if strings.HasPrefix(p, "github.com/redis/go-redis") {
			t.Errorf("scheduler imports Redis client %q — only adapters/queue/redis may", p)
		}
	}
}

func TestJobRunnerDoesNotImportConcreteAdapters(t *testing.T) {
	imports := internalSubtreeImports(t, "../../internal/application/jobrunner")
	for _, p := range imports {
		if strings.HasPrefix(p, "github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/") {
			t.Errorf("jobrunner imports concrete provider adapter %q — must go through ports.SourceAdapter", p)
		}
		if strings.HasPrefix(p, "github.com/konoha-labs/insight-sports-hub/internal/adapters/queue") {
			t.Errorf("jobrunner imports concrete queue adapter %q — must go through ports.JobQueue", p)
		}
		// Sprint 4 — the runner's queue dependency MUST be ports.JobQueue,
		// never a Redis client.
		if strings.HasPrefix(p, "github.com/redis/go-redis") {
			t.Errorf("jobrunner imports Redis client %q — application layer must be transport-agnostic", p)
		}
	}
}

func TestRateLimitDoesNotImportAdapters(t *testing.T) {
	imports := internalSubtreeImports(t, "../../internal/application/ratelimit")
	for _, p := range imports {
		if strings.HasPrefix(p, "github.com/konoha-labs/insight-sports-hub/internal/adapters/") {
			t.Errorf("ratelimit imports adapter package %q — must stay pure application", p)
		}
		if strings.HasPrefix(p, "github.com/redis/go-redis") {
			t.Errorf("ratelimit imports Redis client %q", p)
		}
	}
}

// TestOnlyRedisAdapterImportsGoRedis — Sprint 4 verbatim rule:
// "No application package may import Redis directly. Only adapters
// may depend on Redis libraries." We walk EVERY non-test .go file
// under internal/ and assert that `github.com/redis/go-redis` only
// appears under internal/adapters/queue/redis/.
func TestOnlyRedisAdapterImportsGoRedis(t *testing.T) {
	imports := internalSubtreeImports(t, "../../internal")

	hasRedis := false
	for _, p := range imports {
		if strings.HasPrefix(p, "github.com/redis/go-redis") {
			hasRedis = true
			break
		}
	}

	if !hasRedis {
		t.Log("note: github.com/redis/go-redis not imported anywhere under internal/")
	}

	allowed := []string{
		"/internal/adapters/queue/redis/",
		"/internal/adapters/publishing/",
		// Sprint 6.1 — approved Redis-backed odds infrastructure
		// (response cache, budget counters, change-detection store,
		// runtime mode source). Single allowlisted location so the
		// odds pipeline's Redis touchpoints stay auditable.
		"/internal/adapters/redisinfra/",
	}

	root := "../../internal"

	err := filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}

		if info.IsDir() {
			return nil
		}

		if !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}

		body, rerr := os.ReadFile(p)
		if rerr != nil {
			return rerr
		}

		if strings.Contains(string(body), `"github.com/redis/go-redis`) {

			for _, allowedPath := range allowed {
				if strings.Contains(p, allowedPath) {
					return nil
				}
			}

			t.Errorf(
				"Redis client imported outside approved Redis infrastructure adapters: %s",
				p,
			)
		}

		return nil
	})

	if err != nil {
		t.Fatalf("walk: %v", err)
	}
}

// TestProviderAdaptersDoNotReadPollOrRatePolicy enforces the spec's
// "adapters never know polling intervals / quotas" rule by scanning
// provider package files for references to the policy types.
func TestProviderAdaptersDoNotReadPollOrRatePolicy(t *testing.T) {
	forbiddenSubstrings := []string{
		"syncdom.PollPolicy",
		"syncdom.RateLimitPolicy",
		"sync.PollPolicy",
		"sync.RateLimitPolicy",
	}
	root := "../../internal/adapters/providers"
	err := filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		if !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		body, rerr := os.ReadFile(p)
		if rerr != nil {
			return rerr
		}
		text := string(body)
		for _, bad := range forbiddenSubstrings {
			if strings.Contains(text, bad) {
				t.Errorf("provider file %s references forbidden policy type %q — adapters must not know intervals or quotas",
					p, bad)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk providers: %v", err)
	}
}
