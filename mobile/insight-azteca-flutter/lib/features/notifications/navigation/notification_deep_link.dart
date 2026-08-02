// FEATURE-NOTIFICATIONS-V1 Stage 3 — deep-link validation (same posture as
// SEARCH-V1 / COMMUNITIES-V1). The Gateway already validated + set can_open,
// but the client re-validates before navigating (defence in depth) and NEVER
// composes routes. A notification is opened ONLY when can_open is true AND the
// link maps to a real route.
final _supported = <RegExp>[
  RegExp(r'^/users/[^/]+$'),
  RegExp(r'^/hub/community/[^/]+$'),
  RegExp(r'^/discussion/[^/]+$'),
  RegExp(r'^/post/[^/]+$'),
];

bool notificationDeepLinkIsNavigable(String? deepLink) {
  if (deepLink == null || deepLink.isEmpty) return false;
  for (final re in _supported) {
    if (re.hasMatch(deepLink)) return true;
  }
  return false;
}
