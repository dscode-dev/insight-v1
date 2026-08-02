// Azteca Social Foundation integration tests (Part 12).
//
// Covers: SocialApi endpoint contract (incl. follow/mute path-params +
// nested comments), feed global/following + mapping, post-create
// persistence, likes via post-like API, agents list/profile/posts,
// orphan routes disabled, startup diagnostics.

import 'dart:convert';

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:azteca/core/feature_gate.dart';
import 'package:azteca/models/feed.dart';
import 'package:azteca/models/social.dart';
import 'package:azteca/providers/agents_provider.dart';
import 'package:azteca/providers/feed_provider.dart';
import 'package:azteca/providers/live_provider.dart';
import 'package:azteca/providers/notifications_provider.dart';
import 'package:azteca/providers/radar_provider.dart';
import 'package:azteca/providers/post_thread_provider.dart';
import 'package:azteca/providers/reaction_provider.dart';
import 'package:azteca/providers/user_profile_provider.dart';
import 'package:azteca/services/social_mapping.dart';
import 'package:azteca/services/social_service.dart';

// ---- capturing HTTP adapter: records method+path, returns canned JSON ----
class _Captured {
  _Captured(this.method, this.path);
  final String method;
  final String path;
  @override
  String toString() => '$method $path';
}

class _CapturingAdapter implements HttpClientAdapter {
  final List<_Captured> calls = [];
  Map<String, dynamic> response = const {};

  @override
  Future<ResponseBody> fetch(RequestOptions options,
      Stream<List<int>>? requestStream, Future<void>? cancelFuture) async {
    calls.add(_Captured(options.method, options.path));
    return ResponseBody.fromString(
      jsonEncode(response),
      200,
      headers: {
        Headers.contentTypeHeader: ['application/json'],
      },
    );
  }

  @override
  void close({bool force = false}) {}
}

GatewaySocialService _service(_CapturingAdapter adapter) {
  final dio =
      Dio(BaseOptions(baseUrl: 'https://insight.konohalabs.com.br/cloud'))
        ..httpClientAdapter = adapter;
  return GatewaySocialService(dio);
}

// ---- in-memory fake SocialApi for provider-level tests ----
class FakeSocial implements SocialApi {
  FakeSocial({this.global = const [], this.following = const []});
  List<SocialFeedItemDto> global;
  List<SocialFeedItemDto> following;
  final List<String> liked = [];
  final List<String> unliked = [];
  final List<String> followed = [];
  final List<String> muted = [];
  final List<String> createdComments = [];
  SocialPostDto? lastCreated;

  SocialPostDto _post(String id, {String authorType = 'user'}) => SocialPostDto(
        id: id,
        authorId: 'a-$id',
        authorType: authorType,
        content: 'c-$id',
        metadata: const {},
        visibility: 'public',
        createdAt: DateTime.utc(2026, 1, 1),
        likeCount: 0,
        commentCount: 0,
      );

  @override
  Future<SocialFeedPageDto> globalFeed({int? limit, String? cursor}) async =>
      SocialFeedPageDto(items: global, nextCursor: null);
  @override
  Future<SocialFeedPageDto> followingFeed({int? limit, String? cursor}) async =>
      SocialFeedPageDto(items: following, nextCursor: null);

  @override
  Future<List<AgentProfileDto>> listAgents({bool activeOnly = true}) async => [
        const AgentProfileDto(
          id: 'ag1',
          slug: 'ninja',
          name: 'Ninja',
          avatar: '',
          bio: 'b',
          active: true,
          verified: true,
        ),
      ];
  @override
  Future<AgentProfileDto> getAgent(String id) async => AgentProfileDto(
        id: id,
        slug: 'ninja',
        name: 'Ninja',
        avatar: '',
        bio: 'b',
        active: true,
        verified: true,
      );
  @override
  Future<SocialFeedPageDto> agentPosts(String id,
          {int? limit, String? cursor}) async =>
      SocialFeedPageDto(items: [
        SocialFeedItemDto(
          post: _post('p-$id', authorType: 'agent'),
          authorName: 'Ninja',
          authorAvatar: '',
          fromFollowedAgent: true,
          sponsored: false,
        ),
      ]);

  @override
  Future<SocialUserDto> getUser(String id) async => SocialUserDto(
        id: id,
        username: 'u$id',
        displayName: 'User $id',
        initials: 'U',
        accentColor: '#5BA8FF',
        reputation: 7,
        avatarUrl: '',
      );
  @override
  Future<SocialFeedPageDto> userPosts(String id,
          {int? limit, String? cursor}) async =>
      SocialFeedPageDto(items: [
        SocialFeedItemDto(
          post: _post('up-$id'),
          authorName: 'User $id',
          authorAvatar: '',
          fromFollowedAgent: false,
          sponsored: false,
        ),
      ]);

  @override
  Future<void> follow(String targetId) async => followed.add(targetId);
  @override
  Future<void> unfollow(String targetId) async => followed.remove(targetId);
  @override
  Future<void> mute(String targetId) async => muted.add(targetId);
  @override
  Future<void> unmute(String targetId) async => muted.remove(targetId);

  @override
  Future<SocialPostDto> createPost({
    required String content,
    Map<String, String> metadata = const {},
    String visibility = 'public',
  }) async {
    lastCreated = SocialPostDto(
      id: 'server-id-123',
      authorId: 'me',
      authorType: 'user',
      content: content,
      metadata: metadata,
      visibility: visibility,
      createdAt: DateTime.utc(2026, 1, 2),
      likeCount: 0,
      commentCount: 0,
    );
    return lastCreated!;
  }

  @override
  Future<SocialPostDto> getPost(String id) async => _post(id);
  @override
  Future<void> deletePost(String id) async {}

  @override
  Future<SocialCommentDto> createComment({
    required String postId,
    String? parentId,
    required String content,
  }) async {
    createdComments.add('$postId|${parentId ?? ''}|$content');
    return SocialCommentDto(
      id: 'cmt-${createdComments.length}',
      postId: postId,
      parentId: parentId ?? '',
      authorId: 'me',
      authorType: 'user',
      content: content,
      depth: parentId == null ? 1 : 2,
      createdAt: DateTime.utc(2026, 1, 3),
    );
  }

  @override
  Future<List<SocialCommentDto>> listComments(String postId,
          {int? limit, String? cursor}) async =>
      const [];

  @override
  Future<void> like(String postId) async => liked.add(postId);
  @override
  Future<void> unlike(String postId) async => unliked.add(postId);
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

SocialFeedItemDto _item(String id,
        {String authorType = 'user', bool likedByMe = false}) =>
    SocialFeedItemDto(
      likedByMe: likedByMe,
      post: SocialPostDto(
        id: id,
        authorId: 'author-$id',
        authorType: authorType,
        content: 'body-$id',
        metadata: authorType == 'agent'
            ? const {'title': 'T', 'highlights': '["h1","h2"]'}
            : const {},
        visibility: 'public',
        createdAt: DateTime.utc(2026, 1, 1),
        likeCount: 3,
        commentCount: 2,
      ),
      authorName: authorType == 'agent' ? 'Ninja' : 'Daniela',
      authorAvatar: '',
      fromFollowedAgent: authorType == 'agent',
      sponsored: false,
    );

ProviderContainer _container(FakeSocial fake) {
  final c = ProviderContainer(
    overrides: [socialApiProvider.overrideWithValue(fake)],
  );
  addTearDown(c.dispose);
  return c;
}

void main() {
  group('SocialApi endpoint contract', () {
    test('follow/unfollow/mute/unmute use PATH PARAMS (no body)', () async {
      final a = _CapturingAdapter();
      final svc = _service(a);
      await svc.follow('t1');
      await svc.unfollow('t2');
      await svc.mute('t3');
      await svc.unmute('t4');
      expect(a.calls.map((c) => c.toString()).toList(), <String>[
        'POST /v1/follow/t1',
        'DELETE /v1/follow/t2',
        'POST /v1/mute/t3',
        'DELETE /v1/mute/t4',
      ]);
    });

    test('comments are nested under the post', () async {
      final a = _CapturingAdapter();
      final svc = _service(a);
      await svc.createComment(postId: 'p1', content: 'hi');
      await svc.listComments('p1');
      expect(a.calls[0].toString(), 'POST /v1/posts/p1/comments');
      expect(a.calls[1].toString(), 'GET /v1/posts/p1/comments');
    });

    test('likes hit the post-like route', () async {
      final a = _CapturingAdapter();
      final svc = _service(a);
      await svc.like('p9');
      await svc.unlike('p9');
      expect(a.calls[0].toString(), 'POST /v1/posts/p9/like');
      expect(a.calls[1].toString(), 'DELETE /v1/posts/p9/like');
    });

    test('feed + agents endpoints', () async {
      final a = _CapturingAdapter()
        ..response = <String, dynamic>{'items': <dynamic>[]};
      final svc = _service(a);
      await svc.globalFeed();
      await svc.followingFeed();
      a.response = <String, dynamic>{'agents': <dynamic>[]};
      await svc.listAgents();
      await svc.getAgent('x');
      a.response = <String, dynamic>{'items': <dynamic>[]};
      await svc.agentPosts('x');
      expect(a.calls.map((c) => c.path).toList(), <String>[
        '/v1/feed/global',
        '/v1/feed/following',
        '/v1/agents',
        '/v1/agents/x',
        '/v1/agents/x/posts',
      ]);
    });

    test('interaction states use Gateway batch endpoint', () async {
      final a = _CapturingAdapter()
        ..response = <String, dynamic>{
          'states': [
            {
              'post_id': 'p1',
              'saved': true,
              'boosted': true,
              'boost_count': 3,
            }
          ],
        };
      final svc = _service(a);
      final states = await svc.interactionStates(['p1']);
      expect(a.calls.single.path, '/v1/posts/interaction-states');
      expect(states['p1']?.saved, isTrue);
      expect(states['p1']?.boosted, isTrue);
      expect(states['p1']?.boostCount, 3);
    });
  });

  group('feed mapping', () {
    test('agent item → agentInsight with title/highlights', () {
      final post = feedItemToFeedPost(_item('1', authorType: 'agent'));
      expect(post.kind, FeedPostKind.agentInsight);
      expect(post.agent, isNotNull);
      expect(post.agent!.title, 'T');
      expect(post.agent!.highlights, ['h1', 'h2']);
      expect(post.reactions.likes, 3);
    });

    test('user item → userOpinion', () {
      final post = feedItemToFeedPost(_item('2'));
      expect(post.kind, FeedPostKind.userOpinion);
      expect(post.agent, isNull);
      expect(post.author.displayName, 'Daniela');
    });
  });

  group('feed provider', () {
    test('global feed maps items', () async {
      final fake = FakeSocial(global: [_item('1'), _item('2')]);
      final c = _container(fake);
      final state = await c.read(feedProvider.future);
      expect(state.items.length, 2);
      expect(state.items.first.id, '1');
    });

    test('switching scope reads the following feed', () async {
      final fake = FakeSocial(
        global: [_item('g')],
        following: [_item('f1'), _item('f2')],
      );
      final c = _container(fake);
      await c.read(feedProvider.future);
      c.read(feedScopeProvider.notifier).state = FeedScope.following;
      final state = await c.read(feedProvider.future);
      expect(state.items.map((e) => e.id), ['f1', 'f2']);
    });
  });

  group('post creation persists', () {
    test('createPost returns a server id (no local_ fake)', () async {
      final fake = FakeSocial();
      final created = await fake.createPost(content: 'hello');
      final post = postToFeedPost(created, authorName: 'Você');
      expect(post.id, 'server-id-123');
      expect(post.id.startsWith('local'), isFalse);
      expect(post.body, 'hello');
    });
  });

  group('likes via post-like API', () {
    test('toggle calls like then unlike', () async {
      final fake = FakeSocial();
      final c = _container(fake);
      final n = c.read(reactionNotifierProvider('p1').notifier);
      await n.toggle();
      expect(fake.liked, ['p1']);
      await n.toggle();
      expect(fake.unliked, ['p1']);
    });
  });

  group('comments via post comments API', () {
    test('addComment posts a top-level comment then a reply', () async {
      final fake = FakeSocial();
      final c = _container(fake);
      await c.read(postThreadProvider('p1').future);
      final n = c.read(postThreadProvider('p1').notifier);
      await n.addComment('top');
      await n.addComment('reply', parentId: 'cmt-1');
      expect(fake.createdComments, ['p1||top', 'p1|cmt-1|reply']);
    });
  });

  group('agents', () {
    test('list / profile / posts', () async {
      final fake = FakeSocial();
      final c = _container(fake);
      final list = await c.read(agentsListProvider.future);
      expect(list.single.name, 'Ninja');
      final prof = await c.read(agentProfileProvider('ag1').future);
      expect(prof.id, 'ag1');
      final posts = await c.read(agentPostsProvider('ag1').future);
      expect(posts.single.kind, FeedPostKind.agentInsight);
    });

    test('follow/mute relation uses correct API', () async {
      final fake = FakeSocial();
      final c = _container(fake);
      final n = c.read(agentRelationProvider('ag1').notifier);
      await n.toggleFollow();
      expect(fake.followed, ['ag1']);
      await n.toggleMute();
      expect(fake.muted, ['ag1']);
    });
  });

  group('liked_by_me', () {
    test('feed item liked_by_me maps to FeedPost.likedByMe', () {
      expect(feedItemToFeedPost(_item('1', likedByMe: true)).likedByMe, isTrue);
      expect(feedItemToFeedPost(_item('2')).likedByMe, isFalse);
    });
  });

  group('user profile', () {
    test('profile + posts load via the user endpoints', () async {
      final fake = FakeSocial();
      final c = _container(fake);
      final user = await c.read(userProfileProvider('u9').future);
      expect(user.id, 'u9');
      final posts = await c.read(userPostsProvider('u9').future);
      expect(posts.single.kind, FeedPostKind.userOpinion);
    });

    test('follow/mute user uses the correct API', () async {
      final fake = FakeSocial();
      final c = _container(fake);
      final n = c.read(userRelationProvider('u9').notifier);
      await n.toggleFollow();
      expect(fake.followed, ['u9']);
      await n.toggleMute();
      expect(fake.muted, ['u9']);
    });
  });

  group('orphan routes disabled by default (no 404 in production)', () {
    test('live / radar / notifications throw FeatureUnavailable', () async {
      final c = ProviderContainer();
      addTearDown(c.dispose);
      // Default test build carries only `social_v1` — the orphan flags
      // are off, so these providers must short-circuit BEFORE any
      // network call.
      await expectLater(
        c.read(liveMatchesProvider.future),
        throwsA(isA<FeatureUnavailable>()),
      );
      await expectLater(
        c.read(radarBundleProvider.future),
        throwsA(isA<FeatureUnavailable>()),
      );
      await expectLater(
        c.read(notificationsProvider.future),
        throwsA(isA<FeatureUnavailable>()),
      );
      expect(isFeatureUnavailable(const FeatureUnavailable('x')), isTrue);
    });
  });
}
