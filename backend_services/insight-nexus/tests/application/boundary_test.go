// Architecture boundary tests — same rules as insight-sport-hub:
//
//   - internal/domain/**      imports NO internal packages
//   - internal/application/** never imports internal/adapters/**
//   - internal/ports          never imports application or adapters
//   - go-redis appears ONLY under internal/adapters/redisstream
//   - pgx appears ONLY under internal/adapters/postgres
package application_test

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const modulePrefix = "github.com/konoha-labs/insight-nexus/internal/"

type rule struct {
	from      string
	forbidden []string
}

var rules = []rule{
	{
		from: modulePrefix + "domain/",
		forbidden: []string{
			modulePrefix + "application/",
			modulePrefix + "adapters/",
			modulePrefix + "ports",
		},
	},
	{
		from:      modulePrefix + "application/",
		forbidden: []string{modulePrefix + "adapters/"},
	},
	{
		from: modulePrefix + "ports",
		forbidden: []string{
			modulePrefix + "adapters/",
			modulePrefix + "application/",
		},
	},
}

func packageImports(t *testing.T, root string) map[string][]string {
	t.Helper()
	out := map[string][]string{}
	err := filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		fset := token.NewFileSet()
		f, perr := parser.ParseFile(fset, p, nil, parser.ImportsOnly)
		if perr != nil {
			return perr
		}
		rel, _ := filepath.Rel(root, filepath.Dir(p))
		pkg := modulePrefix + filepath.ToSlash(rel)
		for _, imp := range f.Imports {
			out[pkg] = append(out[pkg], strings.Trim(imp.Path.Value, `"`))
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk: %v", err)
	}
	return out
}

func TestArchitectureBoundaries(t *testing.T) {
	imports := packageImports(t, "../../internal")
	for _, r := range rules {
		for pkg, imps := range imports {
			if !strings.HasPrefix(pkg, r.from) {
				continue
			}
			for _, imp := range imps {
				for _, forbidden := range r.forbidden {
					if strings.HasPrefix(imp, forbidden) {
						t.Errorf("%s imports %s — violates boundary (%s must not import %s)",
							pkg, imp, r.from, forbidden)
					}
				}
			}
		}
	}
}

func TestInfrastructureClientsConfined(t *testing.T) {
	confinements := map[string]string{
		"github.com/redis/go-redis": "internal/adapters/redisstream",
		"github.com/jackc/pgx":      "internal/adapters/postgres",
	}
	root := "../../internal"
	err := filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() || !strings.HasSuffix(p, ".go") || strings.HasSuffix(p, "_test.go") {
			return nil
		}
		body, rerr := os.ReadFile(p)
		if rerr != nil {
			return rerr
		}
		for client, allowed := range confinements {
			if strings.Contains(string(body), `"`+client) &&
				!strings.Contains(filepath.ToSlash(p), allowed) {
				t.Errorf("%s imported outside %s: %s", client, allowed, p)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk: %v", err)
	}
}

// Nexus consumes ONLY the trend stream: no canonical-event streams may
// be referenced anywhere in the codebase.
func TestNexusNeverTouchesCanonicalStreams(t *testing.T) {
	forbidden := []string{
		"insight:stream:events:match",
		"insight:stream:events:odds",
		"insight:stream:events:context",
	}
	err := filepath.Walk("../../internal", func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(p, ".go") {
			return err
		}
		body, rerr := os.ReadFile(p)
		if rerr != nil {
			return rerr
		}
		for _, stream := range forbidden {
			if strings.Contains(string(body), stream) {
				t.Errorf("Nexus references canonical stream %q in %s — it must consume insight:stream:trends only", stream, p)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk: %v", err)
	}
}

// Sprint 3 — the decision + state engines are ISOLATED: they depend on
// domain types and ports only, never on sibling application packages.
// (The pipeline composes them; they never compose each other.)
func TestDecisionAndStateEnginesIsolated(t *testing.T) {
	imports := packageImports(t, "../../internal")
	isolated := []string{
		modulePrefix + "application/publication",
		modulePrefix + "application/agentstate",
	}
	for _, pkg := range isolated {
		for _, imp := range imports[pkg] {
			if strings.HasPrefix(imp, modulePrefix+"application/") {
				t.Errorf("%s imports sibling application package %s — engines must stay isolated", pkg, imp)
			}
		}
	}
}

// Nexus must never reach into Atlas's database: no SQL referencing the
// atlas schema may exist anywhere in the codebase. Nexus's only Atlas
// surface is the trend stream.
func TestNexusNeverAccessesAtlasDatabase(t *testing.T) {
	forbidden := []string{
		"atlas.trend_events",
		"atlas.trend_lifecycle",
		"atlas.correlated_trends",
		"atlas.pattern_memory",
		"atlas.odds_ticks",
		"FROM atlas.",
		"JOIN atlas.",
	}
	err := filepath.Walk("../../internal", func(p string, info os.FileInfo, err error) error {
		if err != nil || info.IsDir() || !strings.HasSuffix(p, ".go") {
			return err
		}
		body, rerr := os.ReadFile(p)
		if rerr != nil {
			return rerr
		}
		for _, needle := range forbidden {
			if strings.Contains(string(body), needle) {
				t.Errorf("Nexus references Atlas database (%q) in %s", needle, p)
			}
		}
		return nil
	})
	if err != nil {
		t.Fatalf("walk: %v", err)
	}
}
