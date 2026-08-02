// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'discussion_thread.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$DiscussionDetailImpl _$$DiscussionDetailImplFromJson(
        Map<String, dynamic> json) =>
    _$DiscussionDetailImpl(
      id: json['id'] as String,
      title: json['title'] as String,
      body: json['body'] as String,
      communityId: json['community_id'] as String,
      communityName: json['community_name'] as String?,
      communityHandle: json['community_handle'] as String?,
      authorId: json['author_id'] as String,
      authorDisplayName: json['author_display_name'] as String?,
      authorInitials: json['author_initials'] as String?,
      authorAccent: json['author_accent'] as String?,
      matchId: json['match_id'] as String?,
      replyCount: (json['reply_count'] as num).toInt(),
      reactionCount: (json['reaction_count'] as num).toInt(),
      createdAt: DateTime.parse(json['created_at'] as String),
      lastActivityTs: DateTime.parse(json['last_activity_ts'] as String),
    );

Map<String, dynamic> _$$DiscussionDetailImplToJson(
        _$DiscussionDetailImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'title': instance.title,
      'body': instance.body,
      'community_id': instance.communityId,
      if (instance.communityName case final value?) 'community_name': value,
      if (instance.communityHandle case final value?) 'community_handle': value,
      'author_id': instance.authorId,
      if (instance.authorDisplayName case final value?)
        'author_display_name': value,
      if (instance.authorInitials case final value?) 'author_initials': value,
      if (instance.authorAccent case final value?) 'author_accent': value,
      if (instance.matchId case final value?) 'match_id': value,
      'reply_count': instance.replyCount,
      'reaction_count': instance.reactionCount,
      'created_at': instance.createdAt.toIso8601String(),
      'last_activity_ts': instance.lastActivityTs.toIso8601String(),
    };

_$DiscussionMessageImpl _$$DiscussionMessageImplFromJson(
        Map<String, dynamic> json) =>
    _$DiscussionMessageImpl(
      id: json['id'] as String,
      authorId: json['author_id'] as String,
      authorDisplayName: json['author_display_name'] as String?,
      authorInitials: json['author_initials'] as String?,
      authorAccent: json['author_accent'] as String?,
      body: json['body'] as String,
      ts: DateTime.parse(json['ts'] as String),
    );

Map<String, dynamic> _$$DiscussionMessageImplToJson(
        _$DiscussionMessageImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'author_id': instance.authorId,
      if (instance.authorDisplayName case final value?)
        'author_display_name': value,
      if (instance.authorInitials case final value?) 'author_initials': value,
      if (instance.authorAccent case final value?) 'author_accent': value,
      'body': instance.body,
      'ts': instance.ts.toIso8601String(),
    };

_$DiscussionMessagesPageImpl _$$DiscussionMessagesPageImplFromJson(
        Map<String, dynamic> json) =>
    _$DiscussionMessagesPageImpl(
      messages: (json['messages'] as List<dynamic>)
          .map((e) => DiscussionMessage.fromJson(e as Map<String, dynamic>))
          .toList(),
      nextCursor: json['next_cursor'] as String?,
    );

Map<String, dynamic> _$$DiscussionMessagesPageImplToJson(
        _$DiscussionMessagesPageImpl instance) =>
    <String, dynamic>{
      'messages': instance.messages.map((e) => e.toJson()).toList(),
      if (instance.nextCursor case final value?) 'next_cursor': value,
    };
