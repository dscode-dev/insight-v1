// FEATURE-SEARCH-V1 Stage 3 — deep-link validation.
//
// The client uses the Gateway-provided deep_link EXCLUSIVELY (it never composes
// routes from entity_type). Before navigating we verify the link matches a route
// the Azteca router actually serves — an honest guard against a null or an
// unrecognized path. If a Gateway deep_link ever fails this check, the fix is in
// the GATEWAY contract, not a silent client-side translation.
//
// Supported shapes (validated against lib/routing/router.dart):
//   /users/{id}          → userProfile
//   /agents/{id}         → agentProfile
//   /hub/community/{id}  → communityDetail
//   /live/match/{id}     → matchDetail
//   /post/{id}           → postThread
// Competitions deliberately return a null deep_link (no client detail route) →
// non-navigable, rendered informative.

final _supported = <RegExp>[
  RegExp(r'^/users/[^/]+$'),
  RegExp(r'^/agents/[^/]+$'),
  RegExp(r'^/hub/community/[^/]+$'),
  RegExp(r'^/live/match/[^/]+$'),
  RegExp(r'^/post/[^/]+$'),
];

/// True when [deepLink] is non-null and matches a real Azteca route.
bool deepLinkIsNavigable(String? deepLink) {
  if (deepLink == null || deepLink.isEmpty) return false;
  for (final re in _supported) {
    if (re.hasMatch(deepLink)) return true;
  }
  return false;
}
