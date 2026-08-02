// Prompt Builder — Sprint 4 Part 6.
//
// Deterministic, VERSIONED prompt assembly. The same inputs always
// produce byte-identical prompts (sorted keys, fixed templates, no
// timestamps inside the prompt body), so prompt_version + inputs
// fully explain any generation. Bump Version whenever the template
// changes — candidates persist it.
//
// The LLM NEVER decides what to publish: the prompt hands it Atlas's
// already-made decision + facts and asks only for phrasing in the
// agent's voice, as strict JSON matching the Social post structure.
package promptbuilder

import (
	"fmt"
	"sort"
	"strings"

	"github.com/konoha-labs/insight-nexus/internal/application/contextbuilder"
	"github.com/konoha-labs/insight-nexus/internal/domain/draft"
	"github.com/konoha-labs/insight-nexus/internal/domain/persona"
	portllm "github.com/konoha-labs/insight-nexus/internal/ports/llm"
)

// Version — bump on ANY template change.
const Version = "v1"

const (
	maxTokens   = 600
	temperature = 0.3
)

// Input — everything the prompt sees.
type Input struct {
	Persona persona.AgentPersona
	// Draft — the DETERMINISTIC structured draft (Atlas facts already
	// projected by draftgen). The LLM rephrases; it never invents.
	Draft draft.Draft
	// Context — cluster/state/evolution context from the pipeline.
	Context contextbuilder.DraftContext
	// PreviousTitles — the agent's recent publication titles on this
	// story (anti-repetition instruction).
	PreviousTitles []string
}

// Request bundles the provider request with its version.
type Request struct {
	portllm.GenerateRequest
	Version string
}

// Build assembles the versioned prompt. Pure function: deterministic
// for identical inputs.
func Build(in Input) Request {
	system := buildSystem(in.Persona)
	prompt := buildPrompt(in)
	return Request{
		GenerateRequest: portllm.GenerateRequest{
			System:      system,
			Prompt:      prompt,
			MaxTokens:   maxTokens,
			Temperature: temperature,
		},
		Version: Version,
	}
}

func buildSystem(p persona.AgentPersona) string {
	var b strings.Builder
	fmt.Fprintf(&b, "You are %s, a sports intelligence agent on the Insight platform.\n", title(p.Slug))
	fmt.Fprintf(&b, "Expertise: %s\n", p.Expertise)
	fmt.Fprintf(&b, "Writing style: %s\n", p.Style)
	fmt.Fprintf(&b, "Tone: %s\n", p.Tone)
	fmt.Fprintf(&b, "Posting behavior: %s\n", p.PostingBehavior)
	b.WriteString("Hard rules (violations make the output unusable):\n")
	restrictions := append([]string{}, p.Restrictions...)
	sort.Strings(restrictions)
	for _, r := range restrictions {
		fmt.Fprintf(&b, "- %s\n", r)
	}
	b.WriteString("- write in Brazilian Portuguese (pt-BR)\n")
	b.WriteString("- describe what IS happening; never predict outcomes\n")
	b.WriteString("- you do not decide WHETHER to post — that decision was already made\n")
	return b.String()
}

func buildPrompt(in Input) string {
	var b strings.Builder
	b.WriteString("Rewrite the following structured intelligence as a social post in your voice.\n\n")
	fmt.Fprintf(&b, "FACTS (already decided and verified — do not invent beyond them):\n")
	fmt.Fprintf(&b, "- title (deterministic): %s\n", in.Draft.Title)
	fmt.Fprintf(&b, "- summary (deterministic): %s\n", in.Draft.Summary)
	for _, h := range in.Draft.Highlights {
		fmt.Fprintf(&b, "- highlight: %s\n", h)
	}
	fmt.Fprintf(&b, "\nSTORY CONTEXT:\n")
	fmt.Fprintf(&b, "- story type: %s\n", in.Context.ClusterType)
	fmt.Fprintf(&b, "- communication beat: %s (sequence %d in this story)\n",
		in.Context.DraftType, in.Context.Sequence)
	fmt.Fprintf(&b, "- priority band: %s\n", in.Context.Priority)
	if len(in.PreviousTitles) > 0 {
		b.WriteString("\nYOU ALREADY POSTED ABOUT THIS STORY (do not repeat yourself; advance the narrative):\n")
		titles := append([]string{}, in.PreviousTitles...)
		sort.Strings(titles)
		for _, t := range titles {
			fmt.Fprintf(&b, "- %s\n", t)
		}
	}
	b.WriteString(`
Answer with STRICT JSON only (no markdown fences, no commentary):
{
  "title": "max 90 chars, your voice",
  "summary": "1-3 sentences, max 400 chars",
  "highlights": ["up to 3 short factual bullets"],
  "tags": ["up to 4 lowercase context tags"],
  "chart_hints": ["optional: which charts would support this, e.g. implied_probability"]
}
`)
	return b.String()
}

func title(slug string) string {
	if slug == "" {
		return slug
	}
	return strings.ToUpper(slug[:1]) + slug[1:]
}
