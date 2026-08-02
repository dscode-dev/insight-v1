// Social Foundation DTOs — Sprint 2 (Part 4).
//
// Wire shapes mirror the Sprint 3 Social/Gateway contracts 1:1
// (insight-social social.v1 → Gateway REST). DO NOT invent fields —
// when the backend contract evolves, this file evolves with it.
//
// Plain hand-rolled fromJson (no codegen): these DTOs are small, the
// mapping is total, and keeping them codegen-free means contract
// changes are one-file diffs.

/// Mirrors social.v1.AgentProfile.
class AgentProfileDto {
  const AgentProfileDto({
    required this.id,
    required this.slug,
    required this.name,
    required this.avatar,
    required this.bio,
    required this.active,
    required this.verified,
  });

  factory AgentProfileDto.fromJson(Map<String, dynamic> j) =>
      AgentProfileDto(
        id: (j['id'] ?? '').toString(),
        slug: (j['slug'] ?? '').toString(),
        name: (j['name'] ?? '').toString(),
        avatar: (j['avatar'] ?? '').toString(),
        bio: (j['bio'] ?? '').toString(),
        active: j['active'] == true,
        verified: j['verified'] == true,
      );

  final String id;
  final String slug;
  final String name;
  final String avatar;
  final String bio;
  final bool active;
  final bool verified;
}

/// Public user profile (Gateway /v1/users/{id}). No private fields.
class SocialUserDto {
  const SocialUserDto({
    required this.id,
    required this.username,
    required this.displayName,
    required this.initials,
    required this.accentColor,
    required this.reputation,
    required this.avatarUrl,
  });

  factory SocialUserDto.fromJson(Map<String, dynamic> j) => SocialUserDto(
        id: (j['id'] ?? '').toString(),
        username: (j['username'] ?? '').toString(),
        displayName: (j['display_name'] ?? '').toString(),
        initials: (j['initials'] ?? '').toString(),
        accentColor: (j['accent_color'] ?? '#5BA8FF').toString(),
        reputation: (j['reputation'] as num?)?.toInt() ?? 0,
        avatarUrl: (j['avatar_url'] ?? '').toString(),
      );

  final String id;
  final String username;
  final String displayName;
  final String initials;
  final String accentColor;
  final int reputation;
  final String avatarUrl;
}

/// Mirrors social.v1.Post (text-only V1).
class SocialPostDto {
  const SocialPostDto({
    required this.id,
    required this.authorId,
    required this.authorType,
    required this.content,
    required this.metadata,
    required this.visibility,
    required this.createdAt,
    required this.likeCount,
    required this.commentCount,
  });

  factory SocialPostDto.fromJson(Map<String, dynamic> j) => SocialPostDto(
        id: (j['id'] ?? '').toString(),
        authorId: (j['author_id'] ?? '').toString(),
        authorType: (j['author_type'] ?? 'user').toString(),
        content: (j['content'] ?? '').toString(),
        metadata: (j['metadata'] is Map)
            ? (j['metadata'] as Map)
                .map((k, v) => MapEntry(k.toString(), v.toString()))
            : const <String, String>{},
        visibility: (j['visibility'] ?? 'public').toString(),
        createdAt:
            DateTime.tryParse((j['created_at'] ?? '').toString())?.toUtc() ??
                DateTime.now().toUtc(),
        likeCount: (j['like_count'] as num?)?.toInt() ?? 0,
        commentCount: (j['comment_count'] as num?)?.toInt() ?? 0,
      );

  final String id;
  final String authorId;
  final String authorType; // user | agent | admin
  final String content;
  final Map<String, String> metadata;
  final String visibility; // public | competition | private
  final DateTime createdAt;
  final int likeCount;
  final int commentCount;

  bool get isAgent => authorType == 'agent';
}

/// Mirrors social.v1.Comment (post → comment → reply, depth ≤ 2).
class SocialCommentDto {
  const SocialCommentDto({
    required this.id,
    required this.postId,
    required this.parentId,
    required this.authorId,
    required this.authorType,
    required this.content,
    required this.depth,
    required this.createdAt,
  });

  factory SocialCommentDto.fromJson(Map<String, dynamic> j) =>
      SocialCommentDto(
        id: (j['id'] ?? '').toString(),
        postId: (j['post_id'] ?? '').toString(),
        parentId: (j['parent_id'] ?? '').toString(),
        authorId: (j['author_id'] ?? '').toString(),
        authorType: (j['author_type'] ?? 'user').toString(),
        content: (j['content'] ?? '').toString(),
        depth: (j['depth'] as num?)?.toInt() ?? 1,
        createdAt:
            DateTime.tryParse((j['created_at'] ?? '').toString())?.toUtc() ??
                DateTime.now().toUtc(),
      );

  final String id;
  final String postId;
  final String parentId; // empty for top-level comments
  final String authorId;
  final String authorType;
  final String content;
  final int depth;
  final DateTime createdAt;
}

/// Mirrors social.v1.FeedItem — post + denormalized author display.
class SocialFeedItemDto {
  const SocialFeedItemDto({
    required this.post,
    required this.authorName,
    required this.authorAvatar,
    required this.fromFollowedAgent,
    required this.sponsored,
    this.likedByMe = false,
  });

  factory SocialFeedItemDto.fromJson(Map<String, dynamic> j) =>
      SocialFeedItemDto(
        post: SocialPostDto.fromJson(
          (j['post'] as Map<String, dynamic>?) ?? const {},
        ),
        authorName: (j['author_name'] ?? '').toString(),
        authorAvatar: (j['author_avatar'] ?? '').toString(),
        fromFollowedAgent: j['from_followed_agent'] == true,
        sponsored: j['sponsored'] == true,
        likedByMe: j['liked_by_me'] == true,
      );

  final SocialPostDto post;
  final String authorName;
  final String authorAvatar;
  final bool fromFollowedAgent;
  final bool sponsored;
  // Viewer's like state (Gateway feed DTO) — seeds the heart correctly.
  final bool likedByMe;
}

class SocialFeedPageDto {
  const SocialFeedPageDto({required this.items, this.nextCursor});

  factory SocialFeedPageDto.fromJson(Map<String, dynamic> j) =>
      SocialFeedPageDto(
        items: ((j['items'] as List?) ?? const [])
            .whereType<Map<String, dynamic>>()
            .map(SocialFeedItemDto.fromJson)
            .toList(growable: false),
        nextCursor: j['next_cursor'] as String?,
      );

  final List<SocialFeedItemDto> items;
  final String? nextCursor;
}

/// Mirrors social.v1.Relationship (with Sprint 3 mute fields).
class FollowRelationshipDto {
  const FollowRelationshipDto({
    required this.sourceUserId,
    required this.targetUserId,
    required this.muted,
  });

  factory FollowRelationshipDto.fromJson(Map<String, dynamic> j) =>
      FollowRelationshipDto(
        sourceUserId: (j['source_user_id'] ?? '').toString(),
        targetUserId: (j['target_user_id'] ?? '').toString(),
        muted: j['muted'] == true,
      );

  final String sourceUserId;
  final String targetUserId;
  final bool muted;
}
