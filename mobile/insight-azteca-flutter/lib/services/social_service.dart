// Social API — the production client for the Social Foundation,
// reached EXCLUSIVELY through the public Gateway (never Atlas, Sport
// Hub, Nexus or Social directly). Path map (verified 1:1 against
// insight-gateway cmd/gateway/main.go):
//
//   GET    /v1/agents                    → listAgents
//   GET    /v1/agents/:id                 → getAgent
//   GET    /v1/agents/:id/posts           → agentPosts
//   GET    /v1/feed/global                → globalFeed
//   GET    /v1/feed/following             → followingFeed
//   POST   /v1/posts                      → createPost
//   GET    /v1/posts/:id                  → getPost
//   DELETE /v1/posts/:id                  → deletePost
//   POST   /v1/posts/:id/comments         → createComment
//   GET    /v1/posts/:id/comments         → listComments
//   POST   /v1/posts/:id/like             → like
//   DELETE /v1/posts/:id/like             → unlike
//   POST   /v1/follow/:targetId           → follow
//   DELETE /v1/follow/:targetId           → unfollow
//   POST   /v1/mute/:targetId             → mute
//   DELETE /v1/mute/:targetId             → unmute
//
// V1 closure: follow/mute use PATH PARAMS (not a `{target_id}` body),
// and comments are nested under the post. Selection (bottom of file):
// GatewaySocialService in gateway mode; the empty fallback is
// DEV/DEMO-ONLY (mock mode) — never the production path.

import 'package:dio/dio.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/api_mode.dart';
import '../core/logger.dart';
import '../models/social.dart';
import 'gateway_client.dart';

/// The Social surface the app consumes. Implementations MUST keep the
/// wire contract — do not invent fields or semantics here.
abstract interface class SocialApi {
  Future<List<AgentProfileDto>> listAgents({bool activeOnly = true});
  Future<AgentProfileDto> getAgent(String id);
  Future<SocialFeedPageDto> agentPosts(String id, {int? limit, String? cursor});

  Future<SocialUserDto> getUser(String id);
  Future<SocialFeedPageDto> userPosts(String id, {int? limit, String? cursor});

  Future<SocialFeedPageDto> globalFeed({int? limit, String? cursor});
  Future<SocialFeedPageDto> followingFeed({int? limit, String? cursor});

  Future<void> follow(String targetId);
  Future<void> unfollow(String targetId);
  Future<void> mute(String targetId);
  Future<void> unmute(String targetId);

  Future<SocialPostDto> createPost({
    required String content,
    Map<String, String> metadata,
    String visibility,
  });
  Future<SocialPostDto> getPost(String id);
  Future<void> deletePost(String id);

  Future<SocialCommentDto> createComment({
    required String postId,
    String? parentId,
    required String content,
  });
  Future<List<SocialCommentDto>> listComments(String postId,
      {int? limit, String? cursor});

  Future<void> like(String postId);
  Future<void> unlike(String postId);

  // AZTECA-SOCIAL-A — Saved Posts + Boosts. Backend (insight-social) is the
  // single source of truth; these are optimistic-toggle-friendly (idempotent,
  // the server echoes the resulting state). The client never persists locally.
  Future<void> save(String postId);
  Future<void> unsave(String postId);
  Future<void> boost(String postId);
  Future<void> unboost(String postId);
  Future<Map<String, PostInteractionStateDto>> interactionStates(
    List<String> postIds,
  );
  Future<List<SavedPostDto>> savedPosts();

  // AZTECA-IDENTITY-B — enriched Sports Profile (single payload: identity +
  // grouped stats + versioned avatar). GET /v1/users/{id}/sports-profile.
  Future<SportsProfileDto> sportsProfile(String userId);

  // AZTECA-PROFILE-B — authenticated profile write. Returns the authoritative
  // updated display name. Only display_name is writable in V1 (the only Core
  // Identity text field the users schema models). PATCH /v1/users/me.
  Future<String> updateDisplayName(String displayName);
}

/// Grouped statistics for a Sports Profile. All counts are backend-owned.
class SportsProfileStatsDto {
  const SportsProfileStatsDto({
    required this.followers,
    required this.following,
    required this.communities,
    required this.posts,
    required this.signals,
  });

  factory SportsProfileStatsDto.fromJson(Map<String, dynamic> json) =>
      SportsProfileStatsDto(
        followers: (json['followers'] as num?)?.toInt() ?? 0,
        following: (json['following'] as num?)?.toInt() ?? 0,
        communities: (json['communities'] as num?)?.toInt() ?? 0,
        posts: (json['posts'] as num?)?.toInt() ?? 0,
        signals: (json['signals'] as num?)?.toInt() ?? 0,
      );

  final int followers;
  final int following;
  final int communities;
  final int posts;
  final int signals;
}

/// The unified Sports Profile payload. `location`/`favoriteTeam` are null until
/// the backend models them — never fabricated. `avatarUrl` is already versioned
/// server-side (`?v=<epoch>`) so caches bust automatically.
class SportsProfileDto {
  const SportsProfileDto({
    required this.id,
    required this.username,
    required this.displayName,
    required this.initials,
    required this.accentColor,
    required this.reputation,
    required this.role,
    required this.stats,
    this.avatarUrl,
    this.avatarVersion,
    this.location,
    this.favoriteTeam,
  });

  factory SportsProfileDto.fromJson(Map<String, dynamic> json) {
    final stats = json['stats'];
    return SportsProfileDto(
      id: (json['id'] ?? '').toString(),
      username: (json['username'] ?? '').toString(),
      displayName: (json['display_name'] ?? '').toString(),
      initials: (json['initials'] ?? '').toString(),
      accentColor: (json['accent_color'] ?? '#5BA8FF').toString(),
      reputation: (json['reputation'] as num?)?.toInt() ?? 0,
      role: (json['role'] ?? 'supporter').toString(),
      avatarUrl: (json['avatar_url'] as String?)?.isEmpty ?? true
          ? null
          : json['avatar_url'] as String,
      avatarVersion: (json['avatar_version'] as num?)?.toInt(),
      location: (json['location'] as String?)?.isEmpty ?? true
          ? null
          : json['location'] as String,
      favoriteTeam: (json['favorite_team'] as String?)?.isEmpty ?? true
          ? null
          : json['favorite_team'] as String,
      stats: stats is Map<String, dynamic>
          ? SportsProfileStatsDto.fromJson(stats)
          : const SportsProfileStatsDto(
              followers: 0, following: 0, communities: 0, posts: 0, signals: 0),
    );
  }

  final String id;
  final String username;
  final String displayName;
  final String initials;
  final String accentColor;
  final int reputation;
  final String role;
  final String? avatarUrl;
  final int? avatarVersion;
  final String? location;
  final String? favoriteTeam;
  final SportsProfileStatsDto stats;
}

/// Backend-owned save/boost snapshot for one post. Hydrates feed cards after
/// reload; the app never stores this locally.
class PostInteractionStateDto {
  const PostInteractionStateDto({
    required this.postId,
    required this.saved,
    required this.boosted,
    required this.boostCount,
  });

  factory PostInteractionStateDto.fromJson(Map<String, dynamic> json) =>
      PostInteractionStateDto(
        postId: (json['post_id'] ?? '').toString(),
        saved: json['saved'] == true,
        boosted: json['boosted'] == true,
        boostCount: (json['boost_count'] as num?)?.toInt() ?? 0,
      );

  final String postId;
  final bool saved;
  final bool boosted;
  final int boostCount;
}

/// One entry of `GET /v1/me/saved-posts`. Self-contained (joins the post) so a
/// future "Saved" screen can render without N extra fetches.
class SavedPostDto {
  const SavedPostDto({
    required this.postId,
    required this.savedAt,
    required this.content,
    required this.authorId,
  });

  factory SavedPostDto.fromJson(Map<String, dynamic> json) => SavedPostDto(
        postId: (json['post_id'] ?? '').toString(),
        savedAt: DateTime.tryParse((json['saved_at'] ?? '').toString()),
        content: (json['content'] ?? '').toString(),
        authorId: (json['author_id'] ?? '').toString(),
      );

  final String postId;
  final DateTime? savedAt;
  final String content;
  final String authorId;
}

/// Production implementation over the Gateway.
class GatewaySocialService implements SocialApi {
  GatewaySocialService(this._dio);
  final Dio _dio;

  @override
  Future<List<AgentProfileDto>> listAgents({bool activeOnly = true}) async {
    final body = await _dio.getJson(
      '/v1/agents',
      query: {'active_only': activeOnly},
    );
    return _agentList(body);
  }

  @override
  Future<AgentProfileDto> getAgent(String id) async =>
      AgentProfileDto.fromJson(await _dio.getJson('/v1/agents/$id'));

  @override
  Future<SocialFeedPageDto> agentPosts(String id,
      {int? limit, String? cursor}) async {
    final body = await _dio.getJson('/v1/agents/$id/posts', query: {
      if (limit != null) 'limit': limit,
      if (cursor != null) 'cursor': cursor,
    });
    return SocialFeedPageDto.fromJson(body);
  }

  @override
  Future<SocialUserDto> getUser(String id) async =>
      SocialUserDto.fromJson(await _dio.getJson('/v1/users/$id'));

  @override
  Future<SocialFeedPageDto> userPosts(String id,
      {int? limit, String? cursor}) async {
    final body = await _dio.getJson('/v1/users/$id/posts', query: {
      if (limit != null) 'limit': limit,
      if (cursor != null) 'cursor': cursor,
    });
    return SocialFeedPageDto.fromJson(body);
  }

  @override
  Future<SocialFeedPageDto> globalFeed({int? limit, String? cursor}) async {
    final body = await _dio.getJson('/v1/feed/global', query: {
      if (limit != null) 'limit': limit,
      if (cursor != null) 'cursor': cursor,
    });
    return SocialFeedPageDto.fromJson(body);
  }

  @override
  Future<SocialFeedPageDto> followingFeed({int? limit, String? cursor}) async {
    final body = await _dio.getJson('/v1/feed/following', query: {
      if (limit != null) 'limit': limit,
      if (cursor != null) 'cursor': cursor,
    });
    return SocialFeedPageDto.fromJson(body);
  }

  // Follow/mute: PATH PARAMS, no body (Gateway forces the acting user
  // from the token — the target is the only argument).
  @override
  Future<void> follow(String targetId) => _dio.postJson('/v1/follow/$targetId');
  @override
  Future<void> unfollow(String targetId) =>
      _dio.delete<void>('/v1/follow/$targetId');
  @override
  Future<void> mute(String targetId) => _dio.postJson('/v1/mute/$targetId');
  @override
  Future<void> unmute(String targetId) =>
      _dio.delete<void>('/v1/mute/$targetId');

  @override
  Future<SocialPostDto> createPost({
    required String content,
    Map<String, String> metadata = const {},
    String visibility = 'public',
  }) async {
    final body = await _dio.postJson('/v1/posts', body: {
      'content': content,
      'metadata': metadata,
      'visibility': visibility,
    });
    return SocialPostDto.fromJson(body);
  }

  @override
  Future<SocialPostDto> getPost(String id) async =>
      SocialPostDto.fromJson(await _dio.getJson('/v1/posts/$id'));

  @override
  Future<void> deletePost(String id) => _dio.delete<void>('/v1/posts/$id');

  @override
  Future<SocialCommentDto> createComment({
    required String postId,
    String? parentId,
    required String content,
  }) async {
    final body = await _dio.postJson('/v1/posts/$postId/comments', body: {
      if (parentId != null && parentId.isNotEmpty) 'parent_id': parentId,
      'content': content,
    });
    return SocialCommentDto.fromJson(body);
  }

  @override
  Future<List<SocialCommentDto>> listComments(String postId,
      {int? limit, String? cursor}) async {
    final body = await _dio.getJson('/v1/posts/$postId/comments', query: {
      if (limit != null) 'limit': limit,
      if (cursor != null) 'cursor': cursor,
    });
    return ((body['comments'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(SocialCommentDto.fromJson)
        .toList(growable: false);
  }

  @override
  Future<void> like(String postId) => _dio.postJson('/v1/posts/$postId/like');
  @override
  Future<void> unlike(String postId) =>
      _dio.delete<void>('/v1/posts/$postId/like');

  @override
  Future<void> save(String postId) => _dio.postJson('/v1/posts/$postId/save');
  @override
  Future<void> unsave(String postId) =>
      _dio.delete<void>('/v1/posts/$postId/save');
  @override
  Future<void> boost(String postId) => _dio.postJson('/v1/posts/$postId/boost');
  @override
  Future<void> unboost(String postId) =>
      _dio.delete<void>('/v1/posts/$postId/boost');

  @override
  Future<Map<String, PostInteractionStateDto>> interactionStates(
    List<String> postIds,
  ) async {
    final ids = postIds.where((id) => id.trim().isNotEmpty).toSet().toList();
    if (ids.isEmpty) return const {};
    final body = await _dio.getJson('/v1/posts/interaction-states', query: {
      'ids': ids.join(','),
    });
    final states = ((body['states'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(PostInteractionStateDto.fromJson)
        .where((s) => s.postId.isNotEmpty);
    return {for (final state in states) state.postId: state};
  }

  @override
  Future<List<SavedPostDto>> savedPosts() async {
    final body = await _dio.getJson('/v1/me/saved-posts');
    return ((body['saved_posts'] as List?) ?? const [])
        .whereType<Map<String, dynamic>>()
        .map(SavedPostDto.fromJson)
        .toList(growable: false);
  }

  @override
  Future<SportsProfileDto> sportsProfile(String userId) async {
    final body = await _dio.getJson('/v1/users/$userId/sports-profile');
    return SportsProfileDto.fromJson(body);
  }

  @override
  Future<String> updateDisplayName(String displayName) async {
    final body = await _dio.patchJson('/v1/users/me',
        body: {'display_name': displayName});
    // Trust the authoritative echo; fall back to the sent value if absent.
    final v = body['display_name'];
    return (v is String && v.isNotEmpty) ? v : displayName;
  }

  static List<AgentProfileDto> _agentList(Map<String, dynamic> body) =>
      ((body['agents'] as List?) ?? const [])
          .whereType<Map<String, dynamic>>()
          .map(AgentProfileDto.fromJson)
          .toList(growable: false);
}

/// ⚠️ DEV/DEMO-ONLY fallback — NOT a production path. ⚠️
///
/// Selected ONLY in mock/demo mode (ApiMode.isMock), so the app is
/// interactive offline without fabricating server state: reads degrade
/// to empty, writes are local no-ops. StartupDiagnostics forbids this
/// from being reached in a production build.
class DemoFallbackSocialService implements SocialApi {
  DemoFallbackSocialService() {
    L.w('social', 'demo_fallback_social_api_active');
  }

  @override
  Future<List<AgentProfileDto>> listAgents({bool activeOnly = true}) async =>
      const [];
  @override
  Future<AgentProfileDto> getAgent(String id) async => AgentProfileDto(
        id: id,
        slug: '',
        name: '',
        avatar: '',
        bio: '',
        active: true,
        verified: false,
      );
  @override
  Future<SocialFeedPageDto> agentPosts(String id,
          {int? limit, String? cursor}) async =>
      const SocialFeedPageDto(items: []);

  @override
  Future<SocialUserDto> getUser(String id) async => SocialUserDto(
        id: id,
        username: '',
        displayName: '',
        initials: '·',
        accentColor: '#5BA8FF',
        reputation: 0,
        avatarUrl: '',
      );
  @override
  Future<SocialFeedPageDto> userPosts(String id,
          {int? limit, String? cursor}) async =>
      const SocialFeedPageDto(items: []);

  @override
  Future<SocialFeedPageDto> globalFeed({int? limit, String? cursor}) async =>
      const SocialFeedPageDto(items: []);
  @override
  Future<SocialFeedPageDto> followingFeed({int? limit, String? cursor}) async =>
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
      SocialPostDto(
        id: 'local-${DateTime.now().microsecondsSinceEpoch}',
        authorId: 'me',
        authorType: 'user',
        content: content,
        metadata: metadata,
        visibility: visibility,
        createdAt: DateTime.now().toUtc(),
        likeCount: 0,
        commentCount: 0,
      );

  @override
  Future<SocialPostDto> getPost(String id) async => SocialPostDto(
        id: id,
        authorId: '',
        authorType: 'user',
        content: '',
        metadata: const {},
        visibility: 'public',
        createdAt: DateTime.now().toUtc(),
        likeCount: 0,
        commentCount: 0,
      );
  @override
  Future<void> deletePost(String id) async {}

  @override
  Future<SocialCommentDto> createComment({
    required String postId,
    String? parentId,
    required String content,
  }) async =>
      SocialCommentDto(
        id: 'local-${DateTime.now().microsecondsSinceEpoch}',
        postId: postId,
        parentId: parentId ?? '',
        authorId: 'me',
        authorType: 'user',
        content: content,
        depth: parentId == null ? 1 : 2,
        createdAt: DateTime.now().toUtc(),
      );
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
    List<String> postIds,
  ) async =>
      const {};
  @override
  Future<List<SavedPostDto>> savedPosts() async => const [];
  @override
  Future<String> updateDisplayName(String displayName) async => displayName;
  @override
  Future<SportsProfileDto> sportsProfile(String userId) async => SportsProfileDto(
        id: userId,
        username: '',
        displayName: '',
        initials: '·',
        accentColor: '#5BA8FF',
        reputation: 0,
        role: 'supporter',
        stats: const SportsProfileStatsDto(
            followers: 0, following: 0, communities: 0, posts: 0, signals: 0),
      );
}

/// Flag name gating the real Gateway Social routes.
const String kSocialV1Flag = 'social_v1';

/// Production selector: the real Gateway client in gateway mode; the
/// demo fallback ONLY in mock mode (dev/demo). The `social_v1` flag is
/// enforced on at boot by StartupDiagnostics in production.
final socialApiProvider = Provider<SocialApi>((ref) {
  if (ApiMode.current.isLive) {
    return GatewaySocialService(ref.watch(gatewayDioProvider));
  }
  return DemoFallbackSocialService();
});
