package signal

// Source mirrors social.v1.SignalSource. Stored as a lowercase
// varchar in `signals.source` for human inspectability:
//
//	'community' ⇄ SourceCommunity   (default — human post)
//	'expert'    ⇄ SourceExpert      (tipster tier)
//	'model'     ⇄ SourceModel       (agent — Atlas-derived)
//
// Plaza-py used 'user' as the default tag; on cutover we treat 'user'
// rows as SourceCommunity in ParseSource so historical signals come
// through cleanly.
type Source int

const (
	SourceUnspecified Source = 0
	SourceCommunity   Source = 1
	SourceExpert      Source = 2
	SourceModel       Source = 3
)

func (s Source) String() string {
	switch s {
	case SourceCommunity:
		return "community"
	case SourceExpert:
		return "expert"
	case SourceModel:
		return "model"
	default:
		return "unspecified"
	}
}

func ParseSource(s string) Source {
	switch s {
	case "community", "user": // 'user' is the plaza-py legacy label
		return SourceCommunity
	case "expert":
		return SourceExpert
	case "model":
		return SourceModel
	default:
		return SourceUnspecified
	}
}
