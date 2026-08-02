// FEATURE-NOTIFICATIONS-V1 Stage 2 — deep-link validation.
//
// The deeplink is PERSISTED by Social at creation. The Gateway is responsible
// for never handing the client an unusable link: an empty, malformed, or
// unknown-route deeplink is dropped ("") and the notification's can_open is set
// false — the ACTION is removed but the notification is KEPT. One bad link
// never breaks the whole list.
package notificationbff

import "regexp"

// Supported client destinations (must match the Azteca router). Same posture as
// SEARCH-V1 / COMMUNITIES-V1.
var supportedDeepLinks = []*regexp.Regexp{
	regexp.MustCompile(`^/users/[^/]+$`),
	regexp.MustCompile(`^/hub/community/[^/]+$`),
	regexp.MustCompile(`^/discussion/[^/]+$`),
	regexp.MustCompile(`^/post/[^/]+$`),
}

// validDeepLink returns the link if it maps to a real route, else "".
func validDeepLink(link string) string {
	if link == "" {
		return ""
	}
	for _, re := range supportedDeepLinks {
		if re.MatchString(link) {
			return link
		}
	}
	return "" // malformed / unknown route → dropped, notification kept
}
