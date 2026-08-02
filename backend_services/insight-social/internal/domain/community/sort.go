package community

// Sort selects the ordering for a List query.
//
// Mirrors social.v1.CommunityListSort. Lives in the domain so the
// application + infrastructure layers can pass the choice around
// without depending on the proto package.
//
// Unspecified resolves to Newest at the repo — the resolution
// happens at one place (List entry) so any future caller (BFF, CLI,
// admin tool) gets the same default.
type Sort int

const (
	SortUnspecified Sort = 0
	SortNewest      Sort = 1 // ORDER BY created_at DESC, id DESC  (default)
	SortHot         Sort = 2 // ORDER BY active_now DESC, member_count DESC, id DESC
	SortPopular     Sort = 3 // ORDER BY member_count DESC, id DESC
)

// Resolve returns the sort actually applied — replaces SortUnspecified
// with the package default (SortNewest). All non-test callers should
// route through this so the default lives in exactly one spot.
func (s Sort) Resolve() Sort {
	if s == SortUnspecified {
		return SortNewest
	}
	return s
}

func (s Sort) String() string {
	switch s.Resolve() {
	case SortHot:
		return "hot"
	case SortPopular:
		return "popular"
	default:
		return "newest"
	}
}
