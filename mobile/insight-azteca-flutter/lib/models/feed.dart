import 'package:freezed_annotation/freezed_annotation.dart';

import 'match.dart';

part 'feed.freezed.dart';
part 'feed.g.dart';

/// Eight feed kinds. The renderer (`FeedItem`) switches on this enum.
/// Mirrors the Next.js `FeedPostKind` 1:1.
enum FeedPostKind {
  @JsonValue('user_opinion')
  userOpinion,
  @JsonValue('quick_analysis')
  quickAnalysis,
  @JsonValue('match_discussion')
  matchDiscussion,
  @JsonValue('community_signal')
  communitySignal,
  @JsonValue('signal')
  signal,
  @JsonValue('system_insight')
  systemInsight,
  @JsonValue('market_movement')
  marketMovement,
  @JsonValue('agent_insight')
  agentInsight,
  // Stage 5.1 — Sponsored Intelligence Post. Architecture-only for now;
  // a temporary in-app provider injects samples between real items.
  // Treated visually like a normal post; only the "Patrocinado" badge
  // (rendered inside the post header) distinguishes it.
  @JsonValue('sponsored_intelligence')
  sponsoredIntelligence,
}

enum SignalBadgeTone {
  @JsonValue('signal')
  signal,
  @JsonValue('warning')
  warning,
  @JsonValue('success')
  success,
  @JsonValue('info')
  info,
}

/// Mirrors `FeedAgentId` in the Next.js types. We keep it as a string
/// instead of reusing AgentId from insight.dart so that wire renames in
/// one surface don't cascade through unrelated screens.
enum FeedAgentId {
  @JsonValue('scout')
  scout,
  @JsonValue('pulse')
  pulse,
  @JsonValue('momentum')
  momentum,
  @JsonValue('stats')
  stats,
  @JsonValue('history')
  history,
}

@freezed
class SignalBadgeData with _$SignalBadgeData {
  const factory SignalBadgeData({
    required String label,
    required SignalBadgeTone tone,
  }) = _SignalBadgeData;

  factory SignalBadgeData.fromJson(Map<String, dynamic> json) =>
      _$SignalBadgeDataFromJson(json);
}

@freezed
class FeedAuthor with _$FeedAuthor {
  const factory FeedAuthor({
    required String id,
    required String displayName,
    String? username,
    required String initials,
    required String accentColor,
    required bool isSystem,
    int? reputation,
    String? tier,
  }) = _FeedAuthor;

  factory FeedAuthor.fromJson(Map<String, dynamic> json) =>
      _$FeedAuthorFromJson(json);
}

/// Optional rolling-delta tag surfaced inside CrowdSnippet — drives the
/// "↑ 8pp em 10min" affordance.
@freezed
class FeedCrowdDelta with _$FeedCrowdDelta {
  const factory FeedCrowdDelta({
    required String side, // home | draw | away
    required int pp,
    required int windowMinutes,
  }) = _FeedCrowdDelta;

  factory FeedCrowdDelta.fromJson(Map<String, dynamic> json) =>
      _$FeedCrowdDeltaFromJson(json);
}

@freezed
class FeedCrowdSentiment with _$FeedCrowdSentiment {
  const factory FeedCrowdSentiment({
    required double homePct,
    required double drawPct,
    required double awayPct,
    required int participants,
    FeedCrowdDelta? delta,
  }) = _FeedCrowdSentiment;

  factory FeedCrowdSentiment.fromJson(Map<String, dynamic> json) =>
      _$FeedCrowdSentimentFromJson(json);
}

@freezed
class FeedReplyPreviewBody with _$FeedReplyPreviewBody {
  const factory FeedReplyPreviewBody({
    required String authorDisplayName,
    required String text,
  }) = _FeedReplyPreviewBody;

  factory FeedReplyPreviewBody.fromJson(Map<String, dynamic> json) =>
      _$FeedReplyPreviewBodyFromJson(json);
}

@freezed
class FeedReplyPreview with _$FeedReplyPreview {
  const factory FeedReplyPreview({
    required int count,
    FeedReplyPreviewBody? preview,
  }) = _FeedReplyPreview;

  factory FeedReplyPreview.fromJson(Map<String, dynamic> json) =>
      _$FeedReplyPreviewFromJson(json);
}

@freezed
class FeedReactions with _$FeedReactions {
  const factory FeedReactions({
    @Default(0) int likes,
    @Default(0) int replies,
    @Default(0) int shares,
  }) = _FeedReactions;

  factory FeedReactions.fromJson(Map<String, dynamic> json) =>
      _$FeedReactionsFromJson(json);
}

@freezed
class FeedCommunityRef with _$FeedCommunityRef {
  const factory FeedCommunityRef({
    required String id,
    required String handle,
    required String name,
  }) = _FeedCommunityRef;

  factory FeedCommunityRef.fromJson(Map<String, dynamic> json) =>
      _$FeedCommunityRefFromJson(json);
}

/// Agent meta — populated only when kind == agent_insight.
@freezed
class FeedAgentMeta with _$FeedAgentMeta {
  const factory FeedAgentMeta({
    required FeedAgentId id,
    required String label,
    required double confidence,
    int? minute,
    // Sprint 2 (Part 6) — trend-post intelligence fields, mirroring
    // the Trend Contract the agents publish (title/summary land in
    // `title` + the post body; highlights/tags are the structured
    // extras). All optional: plain agent commentary renders without.
    String? title,
    @Default(<String>[]) List<String> highlights,
    @Default(<String>[]) List<String> tags,
  }) = _FeedAgentMeta;

  factory FeedAgentMeta.fromJson(Map<String, dynamic> json) =>
      _$FeedAgentMetaFromJson(json);
}

/// Sponsor meta — populated only when kind == sponsored_intelligence.
///
/// Carries the advertiser display name + optional accent + the small
/// "Patrocinado" label so the wire format can localise this without
/// shipping a new client.
@freezed
class FeedSponsorMeta with _$FeedSponsorMeta {
  const factory FeedSponsorMeta({
    required String name,
    @Default('Patrocinado') String label,
    String? accentColor,
    /// Optional click-through URL. Renderer treats it as opaque — the
    /// tap handler decides whether to open in-app or in the system
    /// browser, with appropriate audit logging.
    String? href,
  }) = _FeedSponsorMeta;

  factory FeedSponsorMeta.fromJson(Map<String, dynamic> json) =>
      _$FeedSponsorMetaFromJson(json);
}

/// Single feed item. The `kind` discriminator drives the renderer; most
/// shared fields are optional so each renderer pulls only what it uses.
@freezed
class FeedPost with _$FeedPost {
  const factory FeedPost({
    required String id,
    required FeedPostKind kind,
    required FeedAuthor author,
    SignalBadgeData? badge,
    required String body,
    MatchSummary? match,
    FeedCrowdSentiment? crowd,
    FeedCommunityRef? community,
    FeedAgentMeta? agent,
    FeedSponsorMeta? sponsor,
    @Default(FeedReactions()) FeedReactions reactions,
    @Default(false) bool likedByMe,
    FeedReplyPreview? replyPreview,
    required DateTime ts,
  }) = _FeedPost;

  factory FeedPost.fromJson(Map<String, dynamic> json) =>
      _$FeedPostFromJson(json);
}

/// Paginated wire shape returned by feed.service / Gateway `/v1/feed`.
@freezed
class FeedPage with _$FeedPage {
  const factory FeedPage({
    required List<FeedPost> items,
    String? nextCursor,
  }) = _FeedPage;

  factory FeedPage.fromJson(Map<String, dynamic> json) =>
      _$FeedPageFromJson(json);
}
