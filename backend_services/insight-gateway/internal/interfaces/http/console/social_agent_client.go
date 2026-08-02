// CONSOLE-SOCIAL-B — internal Social agent-state client. The gateway operator
// command plane forwards the SERVER-DERIVED operator id + correlation id to the
// internal Social HTTP mutation endpoint (Social owns agent_profiles.active).

package console

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"strings"
	"time"
)

// errAgentNotFound is returned when the internal Social endpoint reports 404 for
// an agent id (mapped to a 404 by the command handler).
var errAgentNotFound = errors.New("agent_not_found")

// NewAgentStateSetter returns an agentStateSetter bound to the internal Social
// HTTP base URL. Empty base ⇒ a setter that always reports unconfigured.
func NewAgentStateSetter(
	socialHTTPBase, opsToken string,
) func(context.Context, string, string, string, string, string) error {
	base := strings.TrimRight(socialHTTPBase, "/")
	client := &http.Client{Timeout: 6 * time.Second}
	return func(ctx context.Context, agentID, action, reason, operatorID, correlationID string) error {
		if base == "" {
			return errors.New("social_agent_state_unconfigured")
		}
		verb := map[string]string{"deactivate": "deactivate", "reactivate": "reactivate"}[action]
		if verb == "" {
			return fmt.Errorf("invalid_agent_action: %s", action)
		}
		payload, _ := json.Marshal(map[string]string{
			"reason": reason, "operator_id": operatorID, "correlation_id": correlationID,
		})
		url := base + "/console/social/agents/" + agentID + "/" + verb
		req, err := http.NewRequestWithContext(ctx, http.MethodPost, url, bytes.NewReader(payload))
		if err != nil {
			return err
		}
		req.Header.Set("Content-Type", "application/json")
		req.Header.Set("X-Ops-Token", opsToken)
		if correlationID != "" {
			req.Header.Set("X-Request-Id", correlationID)
		}
		resp, err := client.Do(req)
		if err != nil {
			return err
		}
		defer resp.Body.Close()
		if resp.StatusCode == http.StatusNotFound {
			return errAgentNotFound
		}
		if resp.StatusCode < 200 || resp.StatusCode >= 300 {
			return fmt.Errorf("social_agent_state_status_%d", resp.StatusCode)
		}
		return nil
	}
}
