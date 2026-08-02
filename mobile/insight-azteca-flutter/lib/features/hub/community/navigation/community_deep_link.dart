// FEATURE-COMMUNITIES-V1 Stage 3 — deep-link validation (same posture as
// SEARCH-V1). The client uses the Gateway-provided deep_link EXCLUSIVELY and
// never composes routes. Before navigating we verify the link matches a route
// the Azteca router actually serves. If a Gateway deep_link ever fails this
// check, the fix is the GATEWAY contract, not a silent client-side rewrite.
//
// Supported shapes:
//   /users/{id}          → user profile
//   /hub/community/{id}  → community detail
//   /discussion/{id}     → discussion thread

final _supported = <RegExp>[
  RegExp(r'^/users/[^/]+$'),
  RegExp(r'^/hub/community/[^/]+$'),
  RegExp(r'^/discussion/[^/]+$'),
];

bool communityDeepLinkIsNavigable(String? deepLink) {
  if (deepLink == null || deepLink.isEmpty) return false;
  for (final re in _supported) {
    if (re.hasMatch(deepLink)) return true;
  }
  return false;
}
