package user

// Tier mirrors social.v1.UserTier. We declare it here in the domain
// so the application + infrastructure layers don't have to import
// the proto package — keeping the dependency arrow pointing inward.
type Tier int

const (
	TierUnspecified Tier = 0
	TierRookie      Tier = 1 // 0..40
	TierScout       Tier = 2 // 40..60 (default at reputation = 50)
	TierAnalyst     Tier = 3 // 60..85
	TierOracle      Tier = 4 // 85..100
)

// TierForScore is the canonical derivation. Boundaries inclusive on
// the lower end. Matches the cut-points documented in the User proto.
func TierForScore(reputation int) Tier {
	switch {
	case reputation < 40:
		return TierRookie
	case reputation < 60:
		return TierScout
	case reputation < 85:
		return TierAnalyst
	default:
		return TierOracle
	}
}

// String is for log output only — not part of any wire contract.
func (t Tier) String() string {
	switch t {
	case TierRookie:
		return "rookie"
	case TierScout:
		return "scout"
	case TierAnalyst:
		return "analyst"
	case TierOracle:
		return "oracle"
	default:
		return "unspecified"
	}
}

// ParseTier maps the legacy string label back to a Tier.
// Used during reconstitution because the DB column is a varchar
// ('rookie'|'scout'|'analyst'|'oracle') for human inspectability.
func ParseTier(s string) Tier {
	switch s {
	case "rookie":
		return TierRookie
	case "scout":
		return TierScout
	case "analyst":
		return TierAnalyst
	case "oracle":
		return TierOracle
	default:
		return TierUnspecified
	}
}
