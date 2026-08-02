// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'profile.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$UserStatsImpl _$$UserStatsImplFromJson(Map<String, dynamic> json) =>
    _$UserStatsImpl(
      reputation: (json['reputation'] as num).toInt(),
      posts: (json['posts'] as num).toInt(),
      signals: (json['signals'] as num).toInt(),
      accuracy: (json['accuracy'] as num).toDouble(),
    );

Map<String, dynamic> _$$UserStatsImplToJson(_$UserStatsImpl instance) =>
    <String, dynamic>{
      'reputation': instance.reputation,
      'posts': instance.posts,
      'signals': instance.signals,
      'accuracy': instance.accuracy,
    };

_$UserBadgeImpl _$$UserBadgeImplFromJson(Map<String, dynamic> json) =>
    _$UserBadgeImpl(
      id: json['id'] as String,
      label: json['label'] as String,
      description: json['description'] as String,
      emoji: json['emoji'] as String,
      earnedAt: DateTime.parse(json['earned_at'] as String),
    );

Map<String, dynamic> _$$UserBadgeImplToJson(_$UserBadgeImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'label': instance.label,
      'description': instance.description,
      'emoji': instance.emoji,
      'earned_at': instance.earnedAt.toIso8601String(),
    };

_$ProfileActivityImpl _$$ProfileActivityImplFromJson(
        Map<String, dynamic> json) =>
    _$ProfileActivityImpl(
      id: json['id'] as String,
      kind: $enumDecode(_$ProfileActivityKindEnumMap, json['kind']),
      title: json['title'] as String,
      body: json['body'] as String,
      ts: DateTime.parse(json['ts'] as String),
    );

Map<String, dynamic> _$$ProfileActivityImplToJson(
        _$ProfileActivityImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'kind': _$ProfileActivityKindEnumMap[instance.kind]!,
      'title': instance.title,
      'body': instance.body,
      'ts': instance.ts.toIso8601String(),
    };

const _$ProfileActivityKindEnumMap = {
  ProfileActivityKind.post: 'post',
  ProfileActivityKind.signal: 'signal',
  ProfileActivityKind.reply: 'reply',
  ProfileActivityKind.badgeEarned: 'badge_earned',
};

_$ProfileBundleImpl _$$ProfileBundleImplFromJson(Map<String, dynamic> json) =>
    _$ProfileBundleImpl(
      stats: UserStats.fromJson(json['stats'] as Map<String, dynamic>),
      badges: (json['badges'] as List<dynamic>)
          .map((e) => UserBadge.fromJson(e as Map<String, dynamic>))
          .toList(),
      activity: (json['activity'] as List<dynamic>)
          .map((e) => ProfileActivity.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$$ProfileBundleImplToJson(_$ProfileBundleImpl instance) =>
    <String, dynamic>{
      'stats': instance.stats.toJson(),
      'badges': instance.badges.map((e) => e.toJson()).toList(),
      'activity': instance.activity.map((e) => e.toJson()).toList(),
    };
