// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'radar.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$TrendingMatchImpl _$$TrendingMatchImplFromJson(Map<String, dynamic> json) =>
    _$TrendingMatchImpl(
      summary: MatchSummary.fromJson(json['summary'] as Map<String, dynamic>),
      reason: json['reason'] as String,
    );

Map<String, dynamic> _$$TrendingMatchImplToJson(_$TrendingMatchImpl instance) =>
    <String, dynamic>{
      'summary': instance.summary.toJson(),
      'reason': instance.reason,
    };

_$MarketMovementImpl _$$MarketMovementImplFromJson(Map<String, dynamic> json) =>
    _$MarketMovementImpl(
      id: json['id'] as String,
      matchId: json['match_id'] as String,
      matchLabel: json['match_label'] as String,
      league: json['league'] as String,
      direction: $enumDecode(_$MovementDirectionEnumMap, json['direction']),
      summary: json['summary'] as String,
      magnitude: (json['magnitude'] as num).toDouble(),
      ts: DateTime.parse(json['ts'] as String),
    );

Map<String, dynamic> _$$MarketMovementImplToJson(
        _$MarketMovementImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'match_id': instance.matchId,
      'match_label': instance.matchLabel,
      'league': instance.league,
      'direction': _$MovementDirectionEnumMap[instance.direction]!,
      'summary': instance.summary,
      'magnitude': instance.magnitude,
      'ts': instance.ts.toIso8601String(),
    };

const _$MovementDirectionEnumMap = {
  MovementDirection.compressing: 'compressing',
  MovementDirection.widening: 'widening',
  MovementDirection.reversal: 'reversal',
};

_$CommunitySignalCardImpl _$$CommunitySignalCardImplFromJson(
        Map<String, dynamic> json) =>
    _$CommunitySignalCardImpl(
      id: json['id'] as String,
      authorDisplayName: json['author_display_name'] as String,
      authorAccent: json['author_accent'] as String,
      authorInitials: json['author_initials'] as String,
      body: json['body'] as String,
      matchLabel: json['match_label'] as String,
      confidence: (json['confidence'] as num).toDouble(),
      ts: DateTime.parse(json['ts'] as String),
    );

Map<String, dynamic> _$$CommunitySignalCardImplToJson(
        _$CommunitySignalCardImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'author_display_name': instance.authorDisplayName,
      'author_accent': instance.authorAccent,
      'author_initials': instance.authorInitials,
      'body': instance.body,
      'match_label': instance.matchLabel,
      'confidence': instance.confidence,
      'ts': instance.ts.toIso8601String(),
    };

_$RadarBundleImpl _$$RadarBundleImplFromJson(Map<String, dynamic> json) =>
    _$RadarBundleImpl(
      trending: (json['trending'] as List<dynamic>)
          .map((e) => TrendingMatch.fromJson(e as Map<String, dynamic>))
          .toList(),
      movements: (json['movements'] as List<dynamic>)
          .map((e) => MarketMovement.fromJson(e as Map<String, dynamic>))
          .toList(),
      signals: (json['signals'] as List<dynamic>)
          .map((e) => CommunitySignalCard.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$$RadarBundleImplToJson(_$RadarBundleImpl instance) =>
    <String, dynamic>{
      'trending': instance.trending.map((e) => e.toJson()).toList(),
      'movements': instance.movements.map((e) => e.toJson()).toList(),
      'signals': instance.signals.map((e) => e.toJson()).toList(),
    };
