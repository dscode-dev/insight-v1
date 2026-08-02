package reaction

// Kind mirrors social.v1.ReactionKind. Stored as a lowercase varchar
// in `reactions.kind` for human inspectability + easy CHECK extension
// if more kinds land later.
type Kind int

const (
	KindUnspecified Kind = 0
	KindLike        Kind = 1
)

func (k Kind) String() string {
	switch k {
	case KindLike:
		return "like"
	default:
		return "unspecified"
	}
}

// Resolve maps Unspecified → Like (the only kind today). Server-side
// default lives in one place so any handler that gets Unspecified
// from the wire produces a sensible row.
func (k Kind) Resolve() Kind {
	if k == KindUnspecified {
		return KindLike
	}
	return k
}

func ParseKind(s string) Kind {
	switch s {
	case "like":
		return KindLike
	default:
		return KindUnspecified
	}
}
