package relationship

// Kind mirrors social.v1.RelationshipKind. Stored as a lowercase
// varchar in `relationships.kind`:
//
//	'follow' ⇄ KindFollow
//	'block'  ⇄ KindBlock
type Kind int

const (
	KindUnspecified Kind = 0
	KindFollow      Kind = 1
	KindBlock       Kind = 2
)

func (k Kind) String() string {
	switch k {
	case KindFollow:
		return "follow"
	case KindBlock:
		return "block"
	default:
		return "unspecified"
	}
}

func ParseKind(s string) Kind {
	switch s {
	case "follow":
		return KindFollow
	case "block":
		return KindBlock
	default:
		return KindUnspecified
	}
}
