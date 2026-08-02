// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'notifications.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$AppNotificationImpl _$$AppNotificationImplFromJson(
        Map<String, dynamic> json) =>
    _$AppNotificationImpl(
      id: json['id'] as String,
      kind: $enumDecode(_$NotificationKindEnumMap, json['kind']),
      title: json['title'] as String,
      body: json['body'] as String,
      ts: DateTime.parse(json['ts'] as String),
      read: json['read'] as bool? ?? false,
      deeplink: json['deeplink'] as String?,
    );

Map<String, dynamic> _$$AppNotificationImplToJson(
        _$AppNotificationImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'kind': _$NotificationKindEnumMap[instance.kind]!,
      'title': instance.title,
      'body': instance.body,
      'ts': instance.ts.toIso8601String(),
      'read': instance.read,
      if (instance.deeplink case final value?) 'deeplink': value,
    };

const _$NotificationKindEnumMap = {
  NotificationKind.matchEvent: 'match_event',
  NotificationKind.signalReply: 'signal_reply',
  NotificationKind.communityMention: 'community_mention',
  NotificationKind.agentInsight: 'agent_insight',
  NotificationKind.systemUpdate: 'system_update',
};
