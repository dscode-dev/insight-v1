// Home feed boot + Part 5 refresh behavior tests — Social Foundation.
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/app.dart';
import 'package:azteca/models/auth.dart';
import 'package:azteca/models/social.dart';
import 'package:azteca/providers/auth_provider.dart';
import 'package:azteca/providers/feed_provider.dart';
import 'package:azteca/providers/nav_visibility_provider.dart';
import 'package:azteca/providers/onboarding_provider.dart';
import 'package:azteca/services/social_service.dart';
import 'package:azteca/widgets/fixed_bottom_nav.dart';

class _AuthedAuth extends AuthNotifier {
  @override
  AuthState build() => const AuthState(
        status: AuthStatus.authenticated,
        user: AuthUser(id: 'me', username: 'me', displayName: 'Você'),
      );
}

/// Counts globalFeed calls — proves query-time refresh re-fetches — and
/// returns one deterministic user post.
class _CountingSocial implements SocialApi {
  int globalCalls = 0;

  SocialFeedPageDto _page() => SocialFeedPageDto(items: [
        SocialFeedItemDto(
          post: SocialPostDto(
            id: 'p1',
            authorId: 'u1',
            authorType: 'user',
            content: 'Leitura tática do jogo',
            metadata: const {},
            visibility: 'public',
            createdAt: DateTime.utc(2026, 1, 1),
            likeCount: 0,
            commentCount: 0,
          ),
          authorName: 'Lucas Scout',
          authorAvatar: '',
          fromFollowedAgent: false,
          sponsored: false,
        ),
      ]);

  @override
  Future<SocialFeedPageDto> globalFeed({int? limit, String? cursor}) async {
    globalCalls++;
    return _page();
  }

  @override
  Future<SocialFeedPageDto> followingFeed({int? limit, String? cursor}) async =>
      const SocialFeedPageDto(items: []);

  // Unused by these tests.
  @override
  Future<List<AgentProfileDto>> listAgents({bool activeOnly = true}) async =>
      const [];
  @override
  Future<AgentProfileDto> getAgent(String id) async =>
      throw UnimplementedError();
  @override
  Future<SocialUserDto> getUser(String id) async => throw UnimplementedError();
  @override
  Future<SocialFeedPageDto> userPosts(String id,
          {int? limit, String? cursor}) async =>
      const SocialFeedPageDto(items: []);
  @override
  Future<SocialFeedPageDto> agentPosts(String id,
          {int? limit, String? cursor}) async =>
      const SocialFeedPageDto(items: []);
  @override
  Future<void> follow(String targetId) async {}
  @override
  Future<void> unfollow(String targetId) async {}
  @override
  Future<void> mute(String targetId) async {}
  @override
  Future<void> unmute(String targetId) async {}
  @override
  Future<SocialPostDto> createPost({
    required String content,
    Map<String, String> metadata = const {},
    String visibility = 'public',
  }) async =>
      throw UnimplementedError();
  @override
  Future<SocialPostDto> getPost(String id) async => throw UnimplementedError();
  @override
  Future<void> deletePost(String id) async {}
  @override
  Future<SocialCommentDto> createComment({
    required String postId,
    String? parentId,
    required String content,
  }) async =>
      throw UnimplementedError();
  @override
  Future<List<SocialCommentDto>> listComments(String postId,
          {int? limit, String? cursor}) async =>
      const [];
  @override
  Future<void> like(String postId) async {}
  @override
  Future<void> unlike(String postId) async {}
  @override
  Future<void> save(String postId) async {}
  @override
  Future<void> unsave(String postId) async {}
  @override
  Future<void> boost(String postId) async {}
  @override
  Future<void> unboost(String postId) async {}
  @override
  Future<Map<String, PostInteractionStateDto>> interactionStates(
          List<String> postIds) async =>
      const {};
  @override
  Future<List<SavedPostDto>> savedPosts() async => const [];
  @override
  Future<String> updateDisplayName(String displayName) async => displayName;
  @override
  Future<SportsProfileDto> sportsProfile(String userId) async => SportsProfileDto(
        id: userId, username: '', displayName: '', initials: 'X',
        accentColor: '#5BA8FF', reputation: 0, role: 'supporter',
        stats: const SportsProfileStatsDto(
            followers: 0, following: 0, communities: 0, posts: 0, signals: 0),
      );
}

Future<void> _pump(WidgetTester tester, _CountingSocial social) async {
  await tester.pumpWidget(ProviderScope(
    overrides: [
      onboardingStatusProvider.overrideWith((ref) async => true),
      authProvider.overrideWith(_AuthedAuth.new),
      socialApiProvider.overrideWithValue(social),
    ],
    child: const InsightApp(),
  ));
  for (var i = 0; i < 10; i++) {
    await tester.pump(const Duration(milliseconds: 100));
  }
}

void main() {
  testWidgets('home boots from the global feed and renders post content',
      (tester) async {
    final social = _CountingSocial();
    await _pump(tester, social);

    expect(find.text('Postar'), findsOneWidget,
        reason: 'compose FAB must show its expanded label at scroll offset 0');
    expect(find.text('Lucas Scout'), findsOneWidget,
        reason: 'the mapped global-feed post must render');
    expect(find.byType(FixedBottomNav), findsOneWidget);
    expect(social.globalCalls, 1);
  });

  testWidgets(
      'Part 5: re-tapping Home while on Home refreshes the feed and '
      'clears the pending pill', (tester) async {
    final social = _CountingSocial();
    await _pump(tester, social);
    expect(social.globalCalls, 1);

    final container = ProviderScope.containerOf(
      tester.element(find.byType(FixedBottomNav)),
    );
    container.read(pendingNewPostsProvider.notifier).state = 3;
    container.read(homeRetapTickProvider.notifier).state++;
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    expect(social.globalCalls, 2,
        reason: 'Home re-tap must reload page 1 at query time');
    expect(container.read(pendingNewPostsProvider), 0,
        reason: 'manual refresh clears the new-posts affordance');
  });

  testWidgets('tapping the new-posts pill refreshes the feed', (tester) async {
    final social = _CountingSocial();
    await _pump(tester, social);
    expect(social.globalCalls, 1);

    final container = ProviderScope.containerOf(
      tester.element(find.byType(FixedBottomNav)),
    );
    container.read(pendingNewPostsProvider.notifier).state = 2;
    for (var i = 0; i < 6; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    await tester.tap(find.textContaining('novos posts'), warnIfMissed: false);
    for (var i = 0; i < 8; i++) {
      await tester.pump(const Duration(milliseconds: 100));
    }

    expect(social.globalCalls, 2);
    expect(container.read(pendingNewPostsProvider), 0);
  });
}
