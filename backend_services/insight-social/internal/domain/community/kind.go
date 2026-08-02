package community

// Kind mirrors social.v1.CommunityKind. Declared in the domain so the
// rest of the layers don't import the proto package.
//
// Storage convention (varchar in DB) preserved from the legacy schema:
//
//	'topic'       ⇄ KindTopic
//	'competition' ⇄ KindCompetition
type Kind int

const (
	KindUnspecified Kind = 0
	KindCompetition Kind = 1 // auto-created when a competition is added
	KindTopic       Kind = 2 // user/curated topical groups
)

func (k Kind) String() string {
	switch k {
	case KindCompetition:
		return "competition"
	case KindTopic:
		return "topic"
	default:
		return "unspecified"
	}
}

func ParseKind(s string) Kind {
	switch s {
	case "competition":
		return KindCompetition
	case "topic":
		return KindTopic
	default:
		return KindUnspecified
	}
}
