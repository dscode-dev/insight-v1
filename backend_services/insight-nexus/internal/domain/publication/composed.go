package publication

import (
	"encoding/json"
	"errors"
	"fmt"
	"strings"
)

// ComposedPost — the LLM-phrased content in the Social Foundation
// post structure (Part 9). No Social-side transformation is needed:
// title/summary/highlights/tags/chart hints map 1:1 onto the agent
// post metadata Azteca already renders.
type ComposedPost struct {
	Title      string   `json:"title"`
	Summary    string   `json:"summary"`
	Highlights []string `json:"highlights"`
	Tags       []string `json:"tags"`
	ChartHints []string `json:"chart_hints"`
}

var ErrMalformedComposition = errors.New("publication: malformed llm output")

// ParseComposedPost decodes the strict-JSON LLM answer. Tolerates
// (and strips) accidental markdown fences; everything else malformed
// is a provider failure and the router fails over.
func ParseComposedPost(text string) (ComposedPost, error) {
	trimmed := strings.TrimSpace(text)
	trimmed = strings.TrimPrefix(trimmed, "```json")
	trimmed = strings.TrimPrefix(trimmed, "```")
	trimmed = strings.TrimSuffix(trimmed, "```")
	trimmed = strings.TrimSpace(trimmed)

	var post ComposedPost
	if err := json.Unmarshal([]byte(trimmed), &post); err != nil {
		return ComposedPost{}, fmt.Errorf("%w: %v", ErrMalformedComposition, err)
	}
	if strings.TrimSpace(post.Title) == "" || strings.TrimSpace(post.Summary) == "" {
		return ComposedPost{}, fmt.Errorf("%w: empty title or summary", ErrMalformedComposition)
	}
	return post, nil
}
