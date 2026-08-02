// Consolidation Sprint 0 Task 7 — legacy dependency boundary.
//
// Playmaker, Pundit, Atrium and Plaza are retired/detached. No active
// service may import them (or code paths named after them) again.
// This test walks every Go file in the module and fails on any import
// path containing a legacy service name.
package architecture_test

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

var legacyNames = []string{"playmaker", "pundit", "atrium", "plaza", "insight-magnus"}

func TestNoLegacyServiceImports(t *testing.T) {
	root, err := filepath.Abs(filepath.Join("..", ".."))
	if err != nil {
		t.Fatal(err)
	}
	err = filepath.Walk(root, func(p string, info os.FileInfo, err error) error {
		if err != nil {
			return err
		}
		if info.IsDir() {
			name := info.Name()
			if name == "vendor" || name == ".git" || name == "gen" {
				return filepath.SkipDir
			}
			return nil
		}
		if !strings.HasSuffix(p, ".go") {
			return nil
		}
		fset := token.NewFileSet()
		f, perr := parser.ParseFile(fset, p, nil, parser.ImportsOnly)
		if perr != nil {
			t.Fatalf("parse %s: %v", p, perr)
		}
		for _, imp := range f.Imports {
			path := strings.ToLower(strings.Trim(imp.Path.Value, `"`))
			for _, legacy := range legacyNames {
				if strings.Contains(path, legacy) {
					rel, _ := filepath.Rel(root, p)
					t.Errorf("%s imports legacy package %s — %s is retired",
						rel, path, legacy)
				}
			}
		}
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
}
