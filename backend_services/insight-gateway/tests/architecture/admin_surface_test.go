package architecture_test

import (
	"os"
	"path/filepath"
	"regexp"
	"sort"
	"strings"
	"testing"
)

// The Gateway's administrative surface: pinned, and shrinking only.
//
//	insight-context.md v2.0 — Insight Gateway
//	Não é responsável por: Administração, Operadores, Console, Atlas,
//	Explorer, Nexus, Auditoria administrativa.
//
// The Gateway carried 41 routes under /v1/console, /v1/operator, /v1/admin and
// /v1/internal. They exist because the Gateway was the platform's only
// administrative backend before the Insight Control Plane existed, and they
// did not all leave at once — each one leaves when its data does.
//
// WHAT ALREADY LEFT. Fifteen /v1/console/social/* GET routes were a pure proxy
// to Social's own console surface. The Control Plane reaches Social directly
// now, and they are gone.
//
// WHY THE REST IS STILL HERE. Ownership. The enforcement commands mutate
// moderation state stored in THIS service (migrations/00004_moderation.sql);
// the operator auth routes read credentials stored here. Deleting the route
// without moving the data would not clean anything up, it would just remove
// the only way to reach data that is still here.
//
// This test exists so that stays a plan rather than a story. The list only
// gets shorter: adding a route means editing this file, which means someone
// decided to.
func TestAdministrativeSurfaceDoesNotGrow(t *testing.T) {
	// Every administrative route the Gateway still serves, and the migration
	// that removes it. Sorted; keep it that way.
	expected := []string{
		// → Control Plane owns operator identity (already the authority;
		//   these remain for the Node Agent's legacy fallback only).
		"/v1/operator/auth/login",
		"/v1/operator/auth/logout",
		"/v1/operator/auth/me",
		"/v1/operator/auth/refresh",

		// → Control Plane owns the audit spine.
		"/v1/console/audit",
		"/v1/console/audit/events",

		// → Control Plane owns Operational Identity and Delegation.
		"/v1/console/identity/delegations",
		"/v1/console/identity/delegations/{id}",
		"/v1/console/identity/resolve",

		// → end-user administration; the credentials live here.
		"/v1/console/admin/operators",
		"/v1/console/admin/sessions",
		"/v1/console/admin/users",

		// → product-plane health aggregate, legitimately the Gateway's.
		"/v1/console/platform/health",

		// → moderation/enforcement: state owned here, doc assigns it to Social.
		"/v1/admin/moderation/actions",
		"/v1/admin/moderation/reports",
		"/v1/admin/moderation/stats",
		"/v1/admin/users/{id}/legal",
		"/v1/console/social/agents/{id}/deactivate",
		"/v1/console/social/agents/{id}/reactivate",
		"/v1/console/social/comments/{id}/hide",
		"/v1/console/social/comments/{id}/restore",
		"/v1/console/social/enforcement/{type}/{id}",
		"/v1/console/social/posts/{id}/hide",
		"/v1/console/social/posts/{id}/restore",
		"/v1/console/social/reports/{id}/dismiss",
		"/v1/console/social/reports/{id}/resolve",
		"/v1/console/social/reports/{id}/review",
		"/v1/console/social/users/{id}/ban",
		"/v1/console/social/users/{id}/suspend",
		"/v1/console/social/users/{id}/unban",
		"/v1/console/social/users/{id}/unsuspend",

		// → DLQ and internal operations, reached by the Control Plane.
		"/v1/console/dlq",
		"/v1/internal/operations/dlq/{id}/replay",
		"/v1/internal/operations/social/agents/{id}/{action}",
		"/v1/internal/operations/social/content/{type}/{id}/{action}",
		"/v1/internal/operations/users/{id}/sessions/revoke",

		// → Anvil moved to the Robozão; Atlas reaches it directly there.
		"/v1/internal/anvil/features/matches/{match_id}",
	}
	sort.Strings(expected)

	found := administrativeRoutes(t)
	sort.Strings(found)

	if strings.Join(found, "\n") == strings.Join(expected, "\n") {
		return
	}

	for _, route := range diff(found, expected) {
		t.Errorf("NEW administrative route on the Gateway: %s\n"+
			"  insight-context.md v2.0 excludes the Gateway from Administração,\n"+
			"  Operadores, Console and Auditoria administrativa. This belongs in\n"+
			"  the Insight Control Plane. If it genuinely has to live here, add it\n"+
			"  to the expected list with the reason.", route)
	}
	for _, route := range diff(expected, found) {
		t.Errorf("administrative route removed but still listed: %s\n"+
			"  Good news — delete it from the expected list in this test.", route)
	}
}

// The fifteen read proxies are gone and must not come back: they are served by
// Console → Control Plane → Social now, and a second path would put
// SOCIAL_OPS_TOKEN back in the Gateway.
func TestSocialConsoleReadProxyIsGone(t *testing.T) {
	source := mainSource(t)
	for _, route := range []string{
		`"/v1/console/social/"+sub`,
		`SocialConsoleProxy`,
	} {
		if strings.Contains(stripComments(source), route) {
			t.Errorf("the Social console read proxy is back (%s).\n"+
				"  Social's read surface is reached by the Control Plane directly;\n"+
				"  proxying it here means this service holds SOCIAL_OPS_TOKEN again.",
				route)
		}
	}
}

// --- helpers ---------------------------------------------------------------

var routeLiteral = regexp.MustCompile(`"(/v1/(?:console|operator|admin|internal)[^"]*)"`)

func mainSource(t *testing.T) string {
	t.Helper()
	path := filepath.Join("..", "..", "cmd", "gateway", "main.go")
	body, err := os.ReadFile(path)
	if err != nil {
		t.Fatalf("read %s: %v", path, err)
	}
	return string(body)
}

// Comments are stripped before matching: this file's own explanation names the
// routes it forbids, and a checker that fails on its own documentation gets
// deleted rather than obeyed.
func stripComments(source string) string {
	var out strings.Builder
	for _, line := range strings.Split(source, "\n") {
		trimmed := strings.TrimSpace(line)
		if strings.HasPrefix(trimmed, "//") {
			continue
		}
		out.WriteString(line)
		out.WriteString("\n")
	}
	return out.String()
}

func administrativeRoutes(t *testing.T) []string {
	t.Helper()
	seen := map[string]struct{}{}
	for _, match := range routeLiteral.FindAllStringSubmatch(stripComments(mainSource(t)), -1) {
		seen[match[1]] = struct{}{}
	}
	out := make([]string, 0, len(seen))
	for route := range seen {
		out = append(out, route)
	}
	return out
}

func diff(a, b []string) []string {
	inB := make(map[string]struct{}, len(b))
	for _, v := range b {
		inB[v] = struct{}{}
	}
	var only []string
	for _, v := range a {
		if _, ok := inB[v]; !ok {
			only = append(only, v)
		}
	}
	return only
}
