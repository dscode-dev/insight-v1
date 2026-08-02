/// All route paths in one place. Strings nowhere else.
///
/// Deeplink mapping (Phase 5):
///   * Custom scheme:  `insight://app/{path}`     (Android+iOS, no domain ownership needed)
///   * Universal link: `https://insight.konohalabs.com/{path}`
///
/// GoRouter's RouteInformationParser uses `Uri.parse(location).path`, so any
/// incoming URI is reduced to its path component — both forms above resolve
/// to the same route table below. No custom parser is required.
///
/// Universal-link verification on iOS additionally needs the
/// `com.apple.developer.associated-domains` entitlement and a hosted
/// `apple-app-site-association` file at the domain root. Both are deferred
/// until production signing is set up; the URL scheme covers dev/test today.
class R {
  const R._();

  // Animated splash shown while `AuthStatus.hydrating`. Continues
  // the native splash visually so the brand handoff is seamless.
  static const String splash = '/splash';

  // Auth flow (no shell, WhatsApp-style).
  // Three sequential screens, all anonymous-accessible:
  //   /auth/phone     → enters phone, requests OTP
  //   /auth/otp       → enters 6-digit code
  //   /auth/username  → only reached for first-time phones (registration)
  // `login` is kept as an alias for /auth/phone so legacy code paths
  // (router redirect, deeplinks) don't break.
  // Azteca-Y.5 Part 2: auth method entry — the landing screen where the
  // operator chooses how to continue (phone today; biometrics/passkeys are
  // prepared but disabled "em breve"). Routes to authPhone on selection.
  static const String authEntry = '/auth/entry';
  static const String authPhone = '/auth/phone';
  static const String authOtp = '/auth/otp';
  static const String authUsername = '/auth/username';
  static const String login = authEntry;
  static const String register = authEntry;

  // Onboarding — Sprint 6.2 Part 3.
  // Four sequential screens shown after the operator authenticates the
  // first time; the onboardingStatusProvider gate controls whether the
  // router redirects here. Skip + Finish persist the same flag so the
  // operator never sees onboarding twice unless explicitly reset.
  static const String onboardingWelcome = '/onboarding/welcome';
  static const String onboardingAbout = '/onboarding/about';
  static const String onboardingCompetitions = '/onboarding/competitions';
  static const String onboardingTeams = '/onboarding/teams';

  // App shell — five tabs.
  static const String home = '/';
  static const String live = '/live';
  static const String radar = '/radar';
  static const String hub = '/hub';
  static const String profile = '/profile';

  // Nested
  static const String matchDetail = '/live/match/:matchId';
  static const String communityDetail = '/hub/community/:communityId';
  static const String settings = '/profile/settings';
  static const String editProfile = '/profile/edit';

  // Top-level overlays (push over the shell, no bottom nav).
  // Discussion thread lives here (not under /hub) so a reply tap from
  // the Home feed doesn't jump tabs — back returns to wherever the
  // user pushed from.
  static const String search = '/search';
  static const String notifications = '/notifications';
  static const String discussionThread = '/discussion/:discussionId';

  // Social Foundation — post comment thread + agents.
  static const String postThread = '/post/:postId';
  static const String agents = '/agents';
  static const String agentProfile = '/agents/:agentId';
  static const String userProfile = '/users/:userId';

  // Helpers for parameterised routes — keep here so callers don't
  // hand-concatenate paths.
  static String matchDetailFor(String id) => '/live/match/$id';
  static String communityDetailFor(String id) => '/hub/community/$id';
  static String discussionThreadFor(String id) => '/discussion/$id';
  static String postThreadFor(String id) => '/post/$id';
  static String agentProfileFor(String id) => '/agents/$id';
  static String userProfileFor(String id) => '/users/$id';
}

/// Index used by the bottom NavigationBar — order matters and must match
/// the branches declared in `router.dart`.
const List<String> kShellBranches = <String>[
  R.home,
  R.live,
  R.radar,
  R.search,
  R.profile,
];

int branchIndexFor(String location) {
  if (location.startsWith(R.live)) return 1;
  if (location.startsWith(R.radar)) return 2;
  if (location.startsWith(R.search)) return 3;
  if (location.startsWith(R.profile)) return 4;
  return 0; // Home is default.
}
