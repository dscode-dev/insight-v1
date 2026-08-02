// FEATURE-SEARCH-V1 Stage 3 — typed Search models.
//
// These mirror the GATEWAY public contract (searchbff DTOs) — the ONLY contract
// the client knows. It never sees Social's internal shapes and never reproduces
// ranking (the Gateway already ordered results / assigned normalized_score).
//
// A result is a Card {entity_type, entity_id, deep_link, normalized_score?,
// data}. `data` is decoded per entity_type into a concrete typed payload — there
// is NO generic Map-based card in the UI.

// Constructors intentionally follow fields in these small DTOs for readability.
// ignore_for_file: sort_constructors_first
import 'package:flutter/foundation.dart';

/// Categories the client understands. `all` is the aggregated view. The VISIBLE
/// set is derived from the backend capabilities, never this enum.
enum SearchCategory { all, users, agents, communities, competitions, matches, posts }

extension SearchCategoryX on SearchCategory {
  String get wire => switch (this) {
        SearchCategory.all => 'all',
        SearchCategory.users => 'users',
        SearchCategory.agents => 'agents',
        SearchCategory.communities => 'communities',
        SearchCategory.competitions => 'competitions',
        SearchCategory.matches => 'matches',
        SearchCategory.posts => 'posts',
      };

  String get labelPtBr => switch (this) {
        SearchCategory.all => 'Tudo',
        SearchCategory.users => 'Pessoas',
        SearchCategory.agents => 'Agentes',
        SearchCategory.communities => 'Comunidades',
        SearchCategory.competitions => 'Competições',
        SearchCategory.matches => 'Partidas',
        SearchCategory.posts => 'Publicações',
      };

  static SearchCategory? fromWire(String w) {
    for (final c in SearchCategory.values) {
      if (c.wire == w) return c;
    }
    return null; // unknown wire category (e.g. a future one) → ignored
  }
}

/// Backend-declared capabilities. The UI shows tabs ONLY for `enabled`
/// (plus All), never a hardcoded list. `blocked` (teams/players) and `trending`
/// are surfaced honestly but produce no tab / no fabricated content.
@immutable
class SearchCapabilities {
  const SearchCapabilities({
    required this.enabled,
    required this.blocked,
    required this.temporarilyUnavailable,
    required this.trending,
  });

  final List<SearchCategory> enabled;
  final Map<String, String> blocked;
  final List<SearchCategory> temporarilyUnavailable;
  final String trending; // "UNAVAILABLE" in V1

  bool get trendingAvailable => trending.toUpperCase() != 'UNAVAILABLE';

  /// Tabs to render: All first, then the enabled categories in backend order.
  List<SearchCategory> get tabs => [SearchCategory.all, ...enabled];

  factory SearchCapabilities.fromJson(Map<String, dynamic> j) {
    List<SearchCategory> parse(dynamic raw) => ((raw as List?) ?? const [])
        .map((e) => SearchCategoryX.fromWire('$e'))
        .whereType<SearchCategory>()
        .toList(growable: false);
    return SearchCapabilities(
      enabled: parse(j['enabled']),
      blocked: ((j['blocked'] as Map?) ?? const {})
          .map((k, v) => MapEntry('$k', '$v')),
      temporarilyUnavailable: parse(j['temporarily_unavailable']),
      trending: (j['trending'] ?? 'UNAVAILABLE').toString(),
    );
  }

  /// Safe fallback when capabilities can't be fetched: show only All + Users
  /// (the safest real category) rather than guessing the full set.
  static const fallback = SearchCapabilities(
    enabled: [SearchCategory.users],
    blocked: {},
    temporarilyUnavailable: [],
    trending: 'UNAVAILABLE',
  );
}

// ---- typed payloads (decoded from Card.data per entity_type) ----

@immutable
class UserHit {
  const UserHit({
    required this.id, required this.username, required this.displayName,
    required this.initials, required this.accentColor, this.avatarUrl,
    required this.reputation, required this.tier, required this.followers,
    required this.isFollowing, required this.followsViewer, required this.mutual,
  });
  final String id, username, displayName, initials, accentColor, tier;
  final String? avatarUrl;
  final int reputation, followers;
  final bool isFollowing, followsViewer, mutual;

  factory UserHit.fromJson(Map<String, dynamic> j) => UserHit(
        id: '${j['id']}', username: '${j['username']}',
        displayName: '${j['display_name']}', initials: '${j['initials']}',
        accentColor: '${j['accent_color'] ?? '#5BA8FF'}',
        avatarUrl: j['avatar_url'] as String?,
        reputation: (j['reputation'] as num?)?.toInt() ?? 0,
        tier: '${j['tier'] ?? ''}',
        followers: (j['followers'] as num?)?.toInt() ?? 0,
        isFollowing: j['is_following'] == true,
        followsViewer: j['follows_viewer'] == true,
        mutual: j['mutual'] == true,
      );
}

@immutable
class AgentHit {
  const AgentHit({
    required this.id, required this.slug, required this.name,
    required this.avatar, required this.bio, required this.active,
    required this.verified,
  });
  final String id, slug, name, avatar, bio;
  final bool active, verified;

  factory AgentHit.fromJson(Map<String, dynamic> j) => AgentHit(
        id: '${j['id']}', slug: '${j['slug']}', name: '${j['name']}',
        avatar: '${j['avatar'] ?? ''}', bio: '${j['bio'] ?? ''}',
        active: j['active'] == true, verified: j['verified'] == true,
      );
}

@immutable
class CommunityHit {
  const CommunityHit({
    required this.id, required this.slug, required this.name,
    required this.topic, required this.kind, required this.memberCount,
    required this.accentColor,
  });
  final String id, slug, name, topic, kind, accentColor;
  final int memberCount;

  factory CommunityHit.fromJson(Map<String, dynamic> j) => CommunityHit(
        id: '${j['id']}', slug: '${j['slug']}', name: '${j['name']}',
        topic: '${j['topic'] ?? ''}', kind: '${j['kind'] ?? ''}',
        memberCount: (j['member_count'] as num?)?.toInt() ?? 0,
        accentColor: '${j['accent_color'] ?? '#5BA8FF'}',
      );
}

@immutable
class CompetitionHit {
  const CompetitionHit({
    required this.id, required this.slug, required this.name,
    required this.shortName, required this.region, required this.accentColor,
    required this.featured, required this.active,
  });
  final String id, slug, name, shortName, region, accentColor;
  final bool featured, active;

  factory CompetitionHit.fromJson(Map<String, dynamic> j) => CompetitionHit(
        id: '${j['id']}', slug: '${j['slug']}', name: '${j['name']}',
        shortName: '${j['short_name'] ?? ''}', region: '${j['region'] ?? ''}',
        accentColor: '${j['accent_color'] ?? '#5BA8FF'}',
        featured: j['featured'] == true, active: j['active'] == true,
      );
}

/// Team CONTEXT of a match (denormalized strings) — never a Team entity.
@immutable
class TeamContext {
  const TeamContext(this.name, this.short, this.color);
  final String name, short, color;
  factory TeamContext.fromJson(Map<String, dynamic> j) =>
      TeamContext('${j['name'] ?? ''}', '${j['short'] ?? ''}', '${j['color'] ?? '#5BA8FF'}');
}

@immutable
class MatchHit {
  const MatchHit({
    required this.matchId, required this.competitionName,
    required this.home, required this.away, required this.kickoffTs,
    required this.state, this.homeScore, this.awayScore,
  });
  final String matchId, competitionName, kickoffTs, state;
  final TeamContext home, away;
  final int? homeScore, awayScore;

  factory MatchHit.fromJson(Map<String, dynamic> j) => MatchHit(
        matchId: '${j['match_id']}', competitionName: '${j['competition_name'] ?? ''}',
        home: TeamContext.fromJson((j['home_team'] as Map?)?.cast<String, dynamic>() ?? const {}),
        away: TeamContext.fromJson((j['away_team'] as Map?)?.cast<String, dynamic>() ?? const {}),
        kickoffTs: '${j['kickoff_ts'] ?? ''}', state: '${j['state'] ?? ''}',
        homeScore: (j['home_score'] as num?)?.toInt(),
        awayScore: (j['away_score'] as num?)?.toInt(),
      );
}

@immutable
class PostHit {
  const PostHit({
    required this.id, required this.authorName, required this.authorAvatar,
    required this.authorType, required this.snippet, required this.createdAt,
    required this.likeCount, required this.commentCount,
  });
  final String id, authorName, authorAvatar, authorType, snippet, createdAt;
  final int likeCount, commentCount;

  factory PostHit.fromJson(Map<String, dynamic> j) => PostHit(
        id: '${j['id']}', authorName: '${j['author_name'] ?? ''}',
        authorAvatar: '${j['author_avatar'] ?? ''}', authorType: '${j['author_type'] ?? 'user'}',
        snippet: '${j['snippet'] ?? ''}', createdAt: '${j['created_at'] ?? ''}',
        likeCount: (j['like_count'] as num?)?.toInt() ?? 0,
        commentCount: (j['comment_count'] as num?)?.toInt() ?? 0,
      );
}

/// One search result: entity identity + backend-built deep link + typed payload.
@immutable
class SearchCard {
  const SearchCard({
    required this.entityType, required this.entityId, this.deepLink,
    this.score, required this.data,
  });
  final String entityType, entityId;
  final String? deepLink; // backend-built; null (e.g. competitions) = non-navigable
  final double? score;
  final Map<String, dynamic> data;

  /// Stable dedupe key for pagination.
  String get key => '$entityType:$entityId';

  factory SearchCard.fromJson(Map<String, dynamic> j) => SearchCard(
        entityType: '${j['entity_type']}', entityId: '${j['entity_id']}',
        deepLink: j['deep_link'] as String?,
        score: (j['normalized_score'] as num?)?.toDouble(),
        data: ((j['data'] as Map?) ?? const {}).cast<String, dynamic>(),
      );

  UserHit asUser() => UserHit.fromJson(data);
  AgentHit asAgent() => AgentHit.fromJson(data);
  CommunityHit asCommunity() => CommunityHit.fromJson(data);
  CompetitionHit asCompetition() => CompetitionHit.fromJson(data);
  MatchHit asMatch() => MatchHit.fromJson(data);
  PostHit asPost() => PostHit.fromJson(data);
}

/// A per-category page (specific tabs).
@immutable
class SearchPage {
  const SearchPage({required this.items, required this.nextCursor});
  final List<SearchCard> items;
  final String nextCursor;
  bool get hasMore => nextCursor.isNotEmpty;

  factory SearchPage.fromJson(Map<String, dynamic> j) => SearchPage(
        items: ((j['items'] as List?) ?? const [])
            .map((e) => SearchCard.fromJson((e as Map).cast<String, dynamic>()))
            .toList(),
        nextCursor: '${j['next_cursor'] ?? ''}',
      );
}

/// The aggregated All result — items already merged/sorted by the Gateway, with
/// per-category cursors and honest partial flags. The client NEVER builds a
/// universal cursor and NEVER re-sorts.
@immutable
class SearchAllResult {
  const SearchAllResult({
    required this.items, required this.cursors,
    required this.partial, required this.failedCategories,
  });
  final List<SearchCard> items;
  final Map<String, String> cursors; // per category
  final bool partial;
  final List<String> failedCategories;

  factory SearchAllResult.fromJson(Map<String, dynamic> j) => SearchAllResult(
        items: ((j['items'] as List?) ?? const [])
            .map((e) => SearchCard.fromJson((e as Map).cast<String, dynamic>()))
            .toList(),
        cursors: ((j['cursors'] as Map?) ?? const {}).map((k, v) => MapEntry('$k', '$v')),
        partial: j['partial'] == true,
        failedCategories: ((j['failed_categories'] as List?) ?? const [])
            .map((e) => '$e').toList(),
      );
}

@immutable
class SearchHistoryItem {
  const SearchHistoryItem(this.query, this.createdAt);
  final String query;
  final String createdAt;
  factory SearchHistoryItem.fromJson(Map<String, dynamic> j) =>
      SearchHistoryItem('${j['query']}', '${j['created_at'] ?? ''}');
}
