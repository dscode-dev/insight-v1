// Provider isolation — Sprint 2 architectural rule.
//
// "Provider adapters cannot import:
//
//	  application normalization
//	  conflict service
//	  confidence service
//	The adapter layer must remain stateless."
//
// Sprint 1 introduced a boundary test that walked internal/**.
// Sprint 2 tightens it specifically for the providers subtree:
//   - no provider may import another provider package
//   - no provider may import internal/application/**
//
// Failure here is a fail-fast, no-fix-required-in-Sprint-3 signal —
// adding the wrong import means the architectural rule was broken.
package adapters_test

import (
	"go/parser"
	"go/token"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

const providersDirRel = "../../internal/adapters/providers"

// providerForbiddenImports — every provider must NOT import any path
// matching one of these prefixes.
var providerForbiddenImports = []string{
	"github.com/konoha-labs/insight-sports-hub/internal/application/",
}

func TestProviderAdaptersAreIsolated(t *testing.T) {
	absRoot, err := filepath.Abs(providersDirRel)
	if err != nil {
		t.Fatalf("resolve providers dir: %v", err)
	}

	// Discover provider package directories (first level under
	// internal/adapters/providers/).
	entries, err := os.ReadDir(absRoot)
	if err != nil {
		t.Fatalf("read providers dir: %v", err)
	}
	providers := make([]string, 0, len(entries))
	for _, e := range entries {
		if e.IsDir() {
			providers = append(providers, e.Name())
		}
	}

	fset := token.NewFileSet()
	for _, providerName := range providers {
		providerDir := filepath.Join(absRoot, providerName)
		ownPath := "github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/" + providerName

		// Build the "sibling provider paths" set this provider must
		// NOT import.
		siblingForbidden := make([]string, 0)
		for _, other := range providers {
			if other == providerName {
				continue
			}
			siblingForbidden = append(siblingForbidden,
				"github.com/konoha-labs/insight-sports-hub/internal/adapters/providers/"+other)
		}

		files, err := walkGo(providerDir)
		if err != nil {
			t.Fatalf("walk %s: %v", providerDir, err)
		}
		for _, f := range files {
			node, err := parser.ParseFile(fset, f, nil, parser.ImportsOnly)
			if err != nil {
				t.Fatalf("parse %s: %v", f, err)
			}
			for _, imp := range node.Imports {
				path := strings.Trim(imp.Path.Value, `"`)

				// Forbidden: application packages.
				for _, bad := range providerForbiddenImports {
					if strings.HasPrefix(path, bad) {
						t.Errorf("isolation violation: %s imports application package %s (provider must be stateless translator)",
							ownPath, path)
					}
				}
				// Forbidden: another provider package.
				for _, sib := range siblingForbidden {
					if strings.HasPrefix(path, sib) {
						t.Errorf("isolation violation: %s imports sibling provider %s (providers must be independent)",
							ownPath, path)
					}
				}
			}
		}
	}
}

func walkGo(root string) ([]string, error) {
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
