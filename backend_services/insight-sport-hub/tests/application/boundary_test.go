// Architecture boundary test — enforces hexagonal rules by parsing
// the import graph of every package under internal/.
//
// Rules:
//   - internal/domain/**       must NOT import internal/application/**
//     must NOT import internal/adapters/**
//     must NOT import internal/ports/**
//   - internal/application/**  must NOT import internal/adapters/**
//   - internal/ports/**        must NOT import internal/adapters/**
//     must NOT import internal/application/**
//
// Adapters are allowed to import anything (they're the leaves of the
// dependency graph). The composition root (cmd/sportshub) is also
// allowed to import everything — that's where the wires meet.
package application_test

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

// repoRoot is two-up from this test file's directory at runtime.
// Using a relative walk keeps the test portable across CI vs local.
const repoRel = "../.."

// rule says "every package matching `from` must NOT import any
// package matching one of `forbidden`".
type rule struct {
	from      string
	forbidden []string
}

var rules = []rule{
	{
		from: "github.com/konoha-labs/insight-sports-hub/internal/domain/",
		forbidden: []string{
			"github.com/konoha-labs/insight-sports-hub/internal/application/",
			"github.com/konoha-labs/insight-sports-hub/internal/adapters/",
			"github.com/konoha-labs/insight-sports-hub/internal/ports",
		},
	},
	{
		from: "github.com/konoha-labs/insight-sports-hub/internal/application/",
		forbidden: []string{
			"github.com/konoha-labs/insight-sports-hub/internal/adapters/",
		},
	},
	{
		from: "github.com/konoha-labs/insight-sports-hub/internal/ports",
		forbidden: []string{
			"github.com/konoha-labs/insight-sports-hub/internal/adapters/",
			"github.com/konoha-labs/insight-sports-hub/internal/application/",
		},
	},
}

func TestArchitectureBoundaries(t *testing.T) {
	fset := token.NewFileSet()
	root, err := filepath.Abs(repoRel)
	if err != nil {
		t.Fatalf("resolve repo root: %v", err)
	}

	// Walk internal/ — every .go file (excluding tests) gets its
	// import block parsed; we check against the rules.
	internalDir := filepath.Join(root, "internal")
	files, err := walkGoFiles(internalDir)
	if err != nil {
		t.Fatalf("walk: %v", err)
	}

	for _, f := range files {
		pkgPath := importPathFor(f, root)

		// Determine which rules apply.
		applicable := []rule{}
		for _, r := range rules {
			if strings.HasPrefix(pkgPath, r.from) {
				applicable = append(applicable, r)
			}
		}
		if len(applicable) == 0 {
			continue
		}

		// Parse the file's imports.
		ast, err := parser.ParseFile(fset, f, nil, parser.ImportsOnly)
		if err != nil {
			t.Fatalf("parse %s: %v", f, err)
		}
		for _, imp := range ast.Imports {
			path := strings.Trim(imp.Path.Value, `"`)
			for _, r := range applicable {
				for _, bad := range r.forbidden {
					if strings.HasPrefix(path, bad) {
						t.Errorf("boundary violation: %s imports %s (rule: %s must not import %s)",
							pkgPath, path, r.from, bad)
					}
				}
			}
		}
	}
}

func walkGoFiles(root string) ([]string, error) {
	var out []string
	err := filepath.Walk(root, func(path string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			return nil
		}
		if strings.HasSuffix(path, ".go") && !strings.HasSuffix(path, "_test.go") {
			out = append(out, path)
		}
		return nil
	})
	return out, err
}

// importPathFor converts an absolute file path into its module-
// import-path equivalent by stripping the repo root + appending the
// module name.
func importPathFor(abs, repoRoot string) string {
	rel, err := filepath.Rel(repoRoot, abs)
	if err != nil {
		return ""
	}
	dir := filepath.Dir(rel)
	// Normalise to forward slashes for the path comparison (works on
	// Windows where filepath uses backslashes).
	dir = filepath.ToSlash(dir)
	return "github.com/konoha-labs/insight-sports-hub/" + dir
}
