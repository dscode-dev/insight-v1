// DraftValidator — Sprint 4 Part 10.
//
// The last gate before a composed post becomes a publication
// candidate. Pure, deterministic rules — every rejection carries a
// machine-readable reason (explainable suppression). Invalid drafts
// NEVER publish.
package draftvalidator

import (
	"fmt"
	"strings"
	"unicode"

	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	"github.com/konoha-labs/insight-nexus/internal/domain/publication"
)

const (
	maxTitleLen     = 120
	maxSummaryLen   = 600
	maxHighlights   = 3
	maxTags         = 4
	minSummaryWords = 3
)

// Forbidden content (platform product rules): betting instructions,
// bookmaker economics, outcome guarantees. Lowercase substrings.
var forbiddenFragments = []string{
	"aposte", "aposta garantida", "stake", "odds garantida",
	"arbitragem", "surebet", "overround", "margem do bookmaker",
	"dinheiro garantido", "lucro garantido", "bet now", "guaranteed win",
}

// Result — the validation verdict.
type Result struct {
	Valid  bool
	Reason string // machine-readable, empty when valid
}

func invalid(format string, args ...any) Result {
	return Result{Valid: false, Reason: fmt.Sprintf(format, args...)}
}

// Validator holds the deterministic rule set.
type Validator struct{}

func New() *Validator { return &Validator{} }

// Validate runs every rule. recentTitles = the agent's recent
// publication titles (duplicate detection / repetition guard).
func (v *Validator) Validate(
	post publication.ComposedPost,
	p persona.AgentPersona,
	recentTitles []string,
) Result {
	title := strings.TrimSpace(post.Title)
	summary := strings.TrimSpace(post.Summary)

	// Empty content.
	if title == "" {
		return invalid("empty_content: title")
	}
	if summary == "" {
		return invalid("empty_content: summary")
	}
	// Length.
	if len([]rune(title)) > maxTitleLen {
		return invalid("length: title %d > %d", len([]rune(title)), maxTitleLen)
	}
	if len([]rune(summary)) > maxSummaryLen {
		return invalid("length: summary %d > %d", len([]rune(summary)), maxSummaryLen)
	}
	if len(strings.Fields(summary)) < minSummaryWords {
		return invalid("length: summary too short")
	}
	if len(post.Highlights) > maxHighlights {
		return invalid("malformed: too many highlights (%d)", len(post.Highlights))
	}
	if len(post.Tags) > maxTags {
		return invalid("malformed: too many tags (%d)", len(post.Tags))
	}
	// Language: pt-BR posts must not be predominantly non-Latin and
	// should not be SCREAMING (spam heuristic).
	if isShouting(title) {
		return invalid("spam: title is all caps")
	}
	if nonLatinHeavy(summary) {
		return invalid("language: summary not Latin-script")
	}
	// Forbidden content — persona restrictions are PRODUCT rules.
	lowerAll := strings.ToLower(title + " " + summary + " " +
		strings.Join(post.Highlights, " "))
	for _, frag := range forbiddenFragments {
		if strings.Contains(lowerAll, frag) {
			return invalid("forbidden_content: %q", frag)
		}
	}
	// Persona consistency: the post must not break the agent's hard
	// restrictions in the most detectable way — score predictions.
	if p.Slug != "" && containsScorePrediction(lowerAll) {
		return invalid("persona: score prediction violates restrictions")
	}
	// Duplicate detection: identical or near-identical title to a
	// recent publication by the same agent.
	normalized := normalizeTitle(title)
	for _, prev := range recentTitles {
		if normalizeTitle(prev) == normalized {
			return invalid("duplicate: title matches recent publication")
		}
	}
	return Result{Valid: true}
}

func normalizeTitle(s string) string {
	s = strings.ToLower(strings.TrimSpace(s))
	return strings.Join(strings.Fields(s), " ")
}

func isShouting(s string) bool {
	letters, upper := 0, 0
	for _, r := range s {
		if unicode.IsLetter(r) {
			letters++
			if unicode.IsUpper(r) {
				upper++
			}
		}
	}
	return letters >= 12 && upper*10 >= letters*9 // ≥90% uppercase
}

func nonLatinHeavy(s string) bool {
	letters, latin := 0, 0
	for _, r := range s {
		if unicode.IsLetter(r) {
			letters++
			if unicode.In(r, unicode.Latin) {
				latin++
			}
		}
	}
	return letters >= 10 && latin*2 < letters // < 50% Latin letters
}

// containsScorePrediction catches "vai ganhar de 2x0"-style phrasing
// (the cheapest deterministic persona-violation detector).
func containsScorePrediction(s string) bool {
	for _, frag := range []string{"vai ganhar de ", "placar final será", "vai ser 2x", "final score will be"} {
		if strings.Contains(s, frag) {
			return true
		}
	}
	return false
}
