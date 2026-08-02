import 'package:flutter/foundation.dart';
import 'package:flutter/cupertino.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../features/agents/agent_profile_screen.dart';
import '../features/agents/agents_list_screen.dart';
import '../features/auth/screens/auth_entry_screen.dart';
import '../features/auth/screens/otp_verify_screen.dart';
import '../features/auth/screens/phone_entry_screen.dart';
import '../features/auth/screens/username_screen.dart';
import '../features/home/home_screen.dart';
import '../features/home/post_thread_screen.dart';
import '../features/hub/community_detail_screen.dart';
import '../features/hub/discussion_thread_screen.dart';
import '../features/hub/hub_screen.dart';
import '../features/live/live_screen.dart';
import '../features/live/match_detail_screen.dart';
import '../features/notifications/notifications_screen.dart';
import '../features/onboarding/onboarding_screens.dart';
import '../features/profile/edit_profile_screen.dart';
import '../features/profile/profile_screen.dart';
import '../features/profile/user_profile_screen.dart';
import '../features/splash/splash_screen.dart';
import '../features/profile/settings_screen.dart';
import '../features/radar/radar_screen.dart';
import '../features/search/search_screen.dart';
import '../models/auth.dart';
import '../providers/auth_provider.dart';
import '../providers/onboarding_provider.dart';
import 'routes.dart';
import 'shell.dart';

/// GoRouter wired to the auth state machine.
///
/// Redirect rules (evaluated on every navigation + whenever AuthStatus
/// changes via `refreshListenable`):
///   * `hydrating` — stays wherever it is; the route layer paints a
///     splash via the auth-state-aware shell builder.
///   * `anonymous` — anything that isn't an /auth/* route redirects to login.
///   * `authenticated` — sees onboarding once, then routes to Home.
///
/// The router itself is built ONCE; `refreshListenable` triggers
/// re-evaluation of `redirect`, never disposes the router.
final routerProvider = Provider<GoRouter>((ref) {
  final refresh = _AuthRefreshNotifier(ref);
  ref.onDispose(refresh.dispose);

  return GoRouter(
    initialLocation: R.home,
    debugLogDiagnostics: false,
    refreshListenable: refresh,
    // Azteca-X Part 5: dismiss the keyboard on every navigation so a field
    // focused on one screen never leaves the keyboard up on the next.
    observers: [_KeyboardDismissObserver()],
    redirect: (context, state) {
      final status = ref.read(authStatusProvider);
      final loc = state.matchedLocation;
      final onAuthRoute = loc.startsWith('/auth/');
      final onOnboardingRoute = loc.startsWith('/onboarding/');
      final onSplash = loc == R.splash;

      if (status == AuthStatus.hydrating) {
        // Park on the animated splash while boot finishes. The refresh
        // listenable re-runs this redirect when status changes; we then
        // bounce out of /splash to the right destination.
        return onSplash ? null : R.splash;
      }
      final onboardingAsync = ref.read(onboardingStatusProvider);
      if (status == AuthStatus.authenticated && onboardingAsync.isLoading) {
        return onSplash ? null : R.splash;
      }
      final onboardingDone = onboardingAsync.maybeWhen(
        data: (v) => v,
        orElse: () => true, // storage failure — never block the app
      );
      if (status == AuthStatus.anonymous) {
        if (onSplash) return R.authEntry;
        if (onOnboardingRoute) return R.authEntry;
        return onAuthRoute ? null : R.authEntry;
      }
      // Authenticated users see onboarding once, after login/registration,
      // so the introduction has product context without blocking auth.
      if (!onboardingDone) {
        return onOnboardingRoute ? null : R.onboardingWelcome;
      }
      if (onSplash) return R.home;
      if (onAuthRoute || onOnboardingRoute) return R.home;
      return null;
    },
    routes: [
      // Animated splash — destination while AuthStatus.hydrating.
      // No bottom nav, no auth gate; the redirect bounces away the
      // moment auth resolves.
      GoRoute(path: R.splash, builder: (_, __) => const SplashScreen()),

      // Onboarding — Sprint 6.2 Part 3. No bottom nav; redirect rule
      // bounces the operator away once `onboardingStatusProvider`
      // resolves to `true`.
      GoRoute(
        path: R.onboardingWelcome,
        builder: (_, __) => const OnboardingWelcomeScreen(),
      ),
      GoRoute(
        path: R.onboardingAbout,
        builder: (_, __) => const OnboardingAboutScreen(),
      ),
      GoRoute(
        path: R.onboardingCompetitions,
        builder: (_, __) => const OnboardingCompetitionsScreen(),
      ),
      GoRoute(
        path: R.onboardingTeams,
        builder: (_, __) => const OnboardingTeamsScreen(),
      ),

      // WhatsApp-style auth — entry (method choice) → phone → OTP → username.
      GoRoute(path: R.authEntry, builder: (_, __) => const AuthEntryScreen()),
      GoRoute(path: R.authPhone, builder: (_, __) => const PhoneEntryScreen()),
      GoRoute(path: R.authOtp, builder: (_, __) => const OtpVerifyScreen()),
      GoRoute(
        path: R.authUsername,
        builder: (_, __) => const UsernameScreen(),
      ),

      // Top-level overlays — pushed via context.push() from any AppBar;
      // no bottom nav, each has its own back button.
      GoRoute(
        path: R.notifications,
        builder: (_, __) => const NotificationsScreen(),
      ),
      // Hub — communities live OUTSIDE the tab bar since Sprint 2
      // (Explore took its slot); pushed from Explore / deep links.
      GoRoute(
        path: R.hub,
        builder: (_, __) => const HubScreen(),
        routes: [
          GoRoute(
            path: 'community/:communityId',
            builder: (context, state) {
              final id = state.pathParameters['communityId']!;
              return CommunityDetailScreen(communityId: id);
            },
          ),
        ],
      ),
      // Discussion thread — top-level so the reply button works from
      // ANY tab (Home feed, Hub list, Profile, etc.) and back returns
      // to wherever the user pushed from instead of jumping to Hub.
      // Legacy discussion thread — DEBUG-ONLY. No production navigation
      // path reaches it (post taps open the Social Foundation post
      // thread). Registered only in debug builds for back-compat /
      // manual inspection of legacy data.
      if (kDebugMode)
        GoRoute(
          path: '/discussion/:discussionId',
          builder: (context, state) {
            final id = state.pathParameters['discussionId']!;
            return DiscussionThreadScreen(discussionId: id);
          },
        ),

      // Social Foundation — post comment thread.
      GoRoute(
        path: R.postThread,
        pageBuilder: (context, state) => CupertinoPage<void>(
          key: state.pageKey,
          child: PostThreadScreen(postId: state.pathParameters['postId']!),
        ),
      ),
      // Social Foundation — user profile.
      GoRoute(
        path: R.userProfile,
        builder: (context, state) =>
            UserProfileScreen(userId: state.pathParameters['userId']!),
      ),
      // Social Foundation — agents.
      GoRoute(
        path: R.agents,
        builder: (_, __) => const AgentsListScreen(),
        routes: [
          GoRoute(
            path: ':agentId',
            builder: (context, state) =>
                AgentProfileScreen(agentId: state.pathParameters['agentId']!),
          ),
        ],
      ),

      StatefulShellRoute.indexedStack(
        builder: (context, state, navShell) => InsightShell(navShell: navShell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(
              path: R.home,
              builder: (_, __) => const HomeScreen(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: R.live,
              builder: (_, __) => const LiveScreen(),
              routes: [
                GoRoute(
                  path: 'match/:matchId',
                  builder: (context, state) {
                    final id = state.pathParameters['matchId']!;
                    return MatchDetailScreen(matchId: id);
                  },
                ),
              ],
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: R.radar,
              builder: (_, __) => const RadarScreen(),
            ),
          ]),
          // Sprint 2 Part 9 — tab 4 is Search/Explore. The Hub keeps
          // living at /hub (kept below as a pushed route) and is
          // reachable from Explore.
          StatefulShellBranch(routes: [
            GoRoute(
              path: R.search,
              builder: (_, __) => const SearchScreen(),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: R.profile,
              builder: (_, __) => const ProfileScreen(),
              routes: [
                GoRoute(
                  path: 'settings',
                  builder: (_, __) => const SettingsScreen(),
                ),
                GoRoute(
                  path: 'edit',
                  builder: (_, __) => const EditProfileScreen(),
                ),
              ],
            ),
          ]),
        ],
      ),
    ],
  );
});

/// Bridges `authStatusProvider` (Riverpod) to GoRouter's `refreshListenable`
/// without rebuilding the router on every auth tick. We subscribe in
/// the constructor and notify when the status enum value flips.
class _AuthRefreshNotifier extends ChangeNotifier {
  _AuthRefreshNotifier(this._ref) {
    _sub = _ref.listen<AuthStatus>(
      authStatusProvider,
      (prev, next) {
        if (prev != next) notifyListeners();
      },
    );
    // Sprint 2 (Part 1): the first-install gate depends on the
    // persisted onboarding flag too — re-run the redirect when it
    // hydrates or flips, or the app can strand on /splash (or flash
    // login) during first launch.
    _onboardingSub = _ref.listen<AsyncValue<bool>>(
      onboardingStatusProvider,
      (prev, next) {
        if (prev != next) notifyListeners();
      },
    );
  }

  final Ref _ref;
  late final ProviderSubscription<AuthStatus> _sub;
  late final ProviderSubscription<AsyncValue<bool>> _onboardingSub;

  @override
  void dispose() {
    _sub.close();
    _onboardingSub.close();
    super.dispose();
  }
}

/// Dismisses the keyboard on any route push/pop/replace (Azteca-X Part 5).
class _KeyboardDismissObserver extends NavigatorObserver {
  void _dismiss() {
    final focus = FocusManager.instance.primaryFocus;
    if (focus != null && focus.hasFocus) focus.unfocus();
  }

  @override
  void didPush(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _dismiss();

  @override
  void didPop(Route<dynamic> route, Route<dynamic>? previousRoute) =>
      _dismiss();

  @override
  void didReplace({Route<dynamic>? newRoute, Route<dynamic>? oldRoute}) =>
      _dismiss();
}
