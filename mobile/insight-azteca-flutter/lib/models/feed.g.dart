// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'feed.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$SignalBadgeDataImpl _$$SignalBadgeDataImplFromJson(
        Map<String, dynamic> json) =>
    _$SignalBadgeDataImpl(
      label: json['label'] as String,
      tone: $enumDecode(_$SignalBadgeToneEnumMap, json['tone']),
    );

Map<String, dynamic> _$$SignalBadgeDataImplToJson(
        _$SignalBadgeDataImpl instance) =>
    <String, dynamic>{
      'label': instance.label,
      'tone': _$SignalBadgeToneEnumMap[instance.tone]!,
    };

const _$SignalBadgeToneEnumMap = {
  SignalBadgeTone.signal: 'signal',
  SignalBadgeTone.warning: 'warning',
  SignalBadgeTone.success: 'success',
  SignalBadgeTone.info: 'info',
};

_$FeedAuthorImpl _$$FeedAuthorImplFromJson(Map<String, dynamic> json) =>
    _$FeedAuthorImpl(
      id: json['id'] as String,
      displayName: json['display_name'] as String,
      username: json['username'] as String?,
      initials: json['initials'] as String,
      accentColor: json['accent_color'] as String,
      isSystem: json['is_system'] as bool,
      reputation: (json['reputation'] as num?)?.toInt(),
      tier: json['tier'] as String?,
    );

Map<String, dynamic> _$$FeedAuthorImplToJson(_$FeedAuthorImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'display_name': instance.displayName,
      if (instance.username case final value?) 'username': value,
      'initials': instance.initials,
      'accent_color': instance.accentColor,
      'is_system': instance.isSystem,
      if (instance.reputation case final value?) 'reputation': value,
      if (instance.tier case final value?) 'tier': value,
    };

_$FeedCrowdDeltaImpl _$$FeedCrowdDeltaImplFromJson(Map<String, dynamic> json) =>
    _$FeedCrowdDeltaImpl(
      side: json['side'] as String,
      pp: (json['pp'] as num).toInt(),
      windowMinutes: (json['window_minutes'] as num).toInt(),
    );

Map<String, dynamic> _$$FeedCrowdDeltaImplToJson(
        _$FeedCrowdDeltaImpl instance) =>
    <String, dynamic>{
      'side': instance.side,
      'pp': instance.pp,
      'window_minutes': instance.windowMinutes,
    };

_$FeedCrowdSentimentImpl _$$FeedCrowdSentimentImplFromJson(
        Map<String, dynamic> json) =>
    _$FeedCrowdSentimentImpl(
      homePct: (json['home_pct'] as num).toDouble(),
      drawPct: (json['draw_pct'] as num).toDouble(),
      awayPct: (json['away_pct'] as num).toDouble(),
      participants: (json['participants'] as num).toInt(),
      delta: json['delta'] == null
          ? null
          : FeedCrowdDelta.fromJson(json['delta'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$$FeedCrowdSentimentImplToJson(
        _$FeedCrowdSentimentImpl instance) =>
    <String, dynamic>{
      'home_pct': instance.homePct,
      'draw_pct': instance.drawPct,
      'away_pct': instance.awayPct,
      'participants': instance.participants,
      if (instance.delta?.toJson() case final value?) 'delta': value,
    };

_$FeedReplyPreviewBodyImpl _$$FeedReplyPreviewBodyImplFromJson(
        Map<String, dynamic> json) =>
    _$FeedReplyPreviewBodyImpl(
      authorDisplayName: json['author_display_name'] as String,
      text: json['text'] as String,
    );

Map<String, dynamic> _$$FeedReplyPreviewBodyImplToJson(
        _$FeedReplyPreviewBodyImpl instance) =>
    <String, dynamic>{
      'author_display_name': instance.authorDisplayName,
      'text': instance.text,
    };

_$FeedReplyPreviewImpl _$$FeedReplyPreviewImplFromJson(
        Map<String, dynamic> json) =>
    _$FeedReplyPreviewImpl(
      count: (json['count'] as num).toInt(),
      preview: json['preview'] == null
          ? null
          : FeedReplyPreviewBody.fromJson(
              json['preview'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$$FeedReplyPreviewImplToJson(
        _$FeedReplyPreviewImpl instance) =>
    <String, dynamic>{
      'count': instance.count,
      if (instance.preview?.toJson() case final value?) 'preview': value,
    };

_$FeedReactionsImpl _$$FeedReactionsImplFromJson(Map<String, dynamic> json) =>
    _$FeedReactionsImpl(
      likes: (json['likes'] as num?)?.toInt() ?? 0,
      replies: (json['replies'] as num?)?.toInt() ?? 0,
      shares: (json['shares'] as num?)?.toInt() ?? 0,
    );

Map<String, dynamic> _$$FeedReactionsImplToJson(_$FeedReactionsImpl instance) =>
    <String, dynamic>{
      'likes': instance.likes,
      'replies': instance.replies,
      'shares': instance.shares,
    };

_$FeedCommunityRefImpl _$$FeedCommunityRefImplFromJson(
        Map<String, dynamic> json) =>
    _$FeedCommunityRefImpl(
      id: json['id'] as String,
      handle: json['handle'] as String,
      name: json['name'] as String,
    );

Map<String, dynamic> _$$FeedCommunityRefImplToJson(
        _$FeedCommunityRefImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'handle': instance.handle,
      'name': instance.name,
    };

_$FeedAgentMetaImpl _$$FeedAgentMetaImplFromJson(Map<String, dynamic> json) =>
    _$FeedAgentMetaImpl(
      id: $enumDecode(_$FeedAgentIdEnumMap, json['id']),
      label: json['label'] as String,
      confidence: (json['confidence'] as num).toDouble(),
      minute: (json['minute'] as num?)?.toInt(),
      title: json['title'] as String?,
      highlights: (json['highlights'] as List<dynamic>?)
              ?.map((e) => e as String)
              .toList() ??
          const <String>[],
      tags:
          (json['tags'] as List<dynamic>?)?.map((e) => e as String).toList() ??
              const <String>[],
    );

Map<String, dynamic> _$$FeedAgentMetaImplToJson(_$FeedAgentMetaImpl instance) =>
    <String, dynamic>{
      'id': _$FeedAgentIdEnumMap[instance.id]!,
      'label': instance.label,
      'confidence': instance.confidence,
      if (instance.minute case final value?) 'minute': value,
      if (instance.title case final value?) 'title': value,
      'highlights': instance.highlights,
      'tags': instance.tags,
    };

const _$FeedAgentIdEnumMap = {
  FeedAgentId.scout: 'scout',
  FeedAgentId.pulse: 'pulse',
  FeedAgentId.momentum: 'momentum',
  FeedAgentId.stats: 'stats',
  FeedAgentId.history: 'history',
};

_$FeedSponsorMetaImpl _$$FeedSponsorMetaImplFromJson(
        Map<String, dynamic> json) =>
    _$FeedSponsorMetaImpl(
      name: json['name'] as String,
      label: json['label'] as String? ?? 'Patrocinado',
      accentColor: json['accent_color'] as String?,
      href: json['href'] as String?,
    );

Map<String, dynamic> _$$FeedSponsorMetaImplToJson(
        _$FeedSponsorMetaImpl instance) =>
    <String, dynamic>{
      'name': instance.name,
      'label': instance.label,
      if (instance.accentColor case final value?) 'accent_color': value,
      if (instance.href case final value?) 'href': value,
    };

_$FeedPostImpl _$$FeedPostImplFromJson(Map<String, dynamic> json) =>
    _$FeedPostImpl(
      id: json['id'] as String,
      kind: $enumDecode(_$FeedPostKindEnumMap, json['kind']),
      author: FeedAuthor.fromJson(json['author'] as Map<String, dynamic>),
      badge: json['badge'] == null
          ? null
          : SignalBadgeData.fromJson(json['badge'] as Map<String, dynamic>),
      body: json['body'] as String,
      match: json['match'] == null
          ? null
          : MatchSummary.fromJson(json['match'] as Map<String, dynamic>),
      crowd: json['crowd'] == null
          ? null
          : FeedCrowdSentiment.fromJson(json['crowd'] as Map<String, dynamic>),
      community: json['community'] == null
          ? null
          : FeedCommunityRef.fromJson(
              json['community'] as Map<String, dynamic>),
      agent: json['agent'] == null
          ? null
          : FeedAgentMeta.fromJson(json['agent'] as Map<String, dynamic>),
      sponsor: json['sponsor'] == null
          ? null
          : FeedSponsorMeta.fromJson(json['sponsor'] as Map<String, dynamic>),
      reactions: json['reactions'] == null
          ? const FeedReactions()
          : FeedReactions.fromJson(json['reactions'] as Map<String, dynamic>),
      likedByMe: json['liked_by_me'] as bool? ?? false,
      replyPreview: json['reply_preview'] == null
          ? null
          : FeedReplyPreview.fromJson(
              json['reply_preview'] as Map<String, dynamic>),
      ts: DateTime.parse(json['ts'] as String),
    );

Map<String, dynamic> _$$FeedPostImplToJson(_$FeedPostImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'kind': _$FeedPostKindEnumMap[instance.kind]!,
      'author': instance.author.toJson(),
      if (instance.badge?.toJson() case final value?) 'badge': value,
      'body': instance.body,
      if (instance.match?.toJson() case final value?) 'match': value,
      if (instance.crowd?.toJson() case final value?) 'crowd': value,
      if (instance.community?.toJson() case final value?) 'community': value,
      if (instance.agent?.toJson() case final value?) 'agent': value,
      if (instance.sponsor?.toJson() case final value?) 'sponsor': value,
      'reactions': instance.reactions.toJson(),
      'liked_by_me': instance.likedByMe,
      if (instance.replyPreview?.toJson() case final value?)
        'reply_preview': value,
      'ts': instance.ts.toIso8601String(),
    };

const _$FeedPostKindEnumMap = {
  FeedPostKind.userOpinion: 'user_opinion',
  FeedPostKind.quickAnalysis: 'quick_analysis',
  FeedPostKind.matchDiscussion: 'match_discussion',
  FeedPostKind.communitySignal: 'community_signal',
  FeedPostKind.signal: 'signal',
  FeedPostKind.systemInsight: 'system_insight',
  FeedPostKind.marketMovement: 'market_movement',
  FeedPostKind.agentInsight: 'agent_insight',
  FeedPostKind.sponsoredIntelligence: 'sponsored_intelligence',
};

_$FeedPageImpl _$$FeedPageImplFromJson(Map<String, dynamic> json) =>
    _$FeedPageImpl(
      items: (json['items'] as List<dynamic>)
          .map((e) => FeedPost.fromJson(e as Map<String, dynamic>))
          .toList(),
      nextCursor: json['next_cursor'] as String?,
    );

Map<String, dynamic> _$$FeedPageImplToJson(_$FeedPageImpl instance) =>
    <String, dynamic>{
      'items': instance.items.map((e) => e.toJson()).toList(),
      if (instance.nextCursor case final value?) 'next_cursor': value,
    };
