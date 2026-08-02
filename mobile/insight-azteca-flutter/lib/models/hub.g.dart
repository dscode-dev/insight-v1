// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'hub.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$CommunityImpl _$$CommunityImplFromJson(Map<String, dynamic> json) =>
    _$CommunityImpl(
      id: json['id'] as String,
      name: json['name'] as String,
      handle: json['handle'] as String,
      accentColor: json['accent_color'] as String,
      activeMembers: (json['active_members'] as num).toInt(),
      description: json['description'] as String?,
    );

Map<String, dynamic> _$$CommunityImplToJson(_$CommunityImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'name': instance.name,
      'handle': instance.handle,
      'accent_color': instance.accentColor,
      'active_members': instance.activeMembers,
      if (instance.description case final value?) 'description': value,
    };

_$DiscussionImpl _$$DiscussionImplFromJson(Map<String, dynamic> json) =>
    _$DiscussionImpl(
      id: json['id'] as String,
      communityHandle: json['community_handle'] as String,
      authorDisplayName: json['author_display_name'] as String,
      authorAccent: json['author_accent'] as String,
      authorInitials: json['author_initials'] as String,
      title: json['title'] as String,
      snippet: json['snippet'] as String,
      replies: (json['replies'] as num).toInt(),
      lastActivityTs: DateTime.parse(json['last_activity_ts'] as String),
    );

Map<String, dynamic> _$$DiscussionImplToJson(_$DiscussionImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'community_handle': instance.communityHandle,
      'author_display_name': instance.authorDisplayName,
      'author_accent': instance.authorAccent,
      'author_initials': instance.authorInitials,
      'title': instance.title,
      'snippet': instance.snippet,
      'replies': instance.replies,
      'last_activity_ts': instance.lastActivityTs.toIso8601String(),
    };

_$TipsterImpl _$$TipsterImplFromJson(Map<String, dynamic> json) =>
    _$TipsterImpl(
      id: json['id'] as String,
      displayName: json['display_name'] as String,
      username: json['username'] as String,
      accentColor: json['accent_color'] as String,
      initials: json['initials'] as String,
      accuracy: (json['accuracy'] as num).toDouble(),
      signals: (json['signals'] as num).toInt(),
      tier: json['tier'] as String,
    );

Map<String, dynamic> _$$TipsterImplToJson(_$TipsterImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'display_name': instance.displayName,
      'username': instance.username,
      'accent_color': instance.accentColor,
      'initials': instance.initials,
      'accuracy': instance.accuracy,
      'signals': instance.signals,
      'tier': instance.tier,
    };

_$HubBundleImpl _$$HubBundleImplFromJson(Map<String, dynamic> json) =>
    _$HubBundleImpl(
      communities: (json['communities'] as List<dynamic>)
          .map((e) => Community.fromJson(e as Map<String, dynamic>))
          .toList(),
      tipsters: (json['tipsters'] as List<dynamic>)
          .map((e) => Tipster.fromJson(e as Map<String, dynamic>))
          .toList(),
      discussions: (json['discussions'] as List<dynamic>)
          .map((e) => Discussion.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$$HubBundleImplToJson(_$HubBundleImpl instance) =>
    <String, dynamic>{
      'communities': instance.communities.map((e) => e.toJson()).toList(),
      'tipsters': instance.tipsters.map((e) => e.toJson()).toList(),
      'discussions': instance.discussions.map((e) => e.toJson()).toList(),
    };

_$CommunityMemberImpl _$$CommunityMemberImplFromJson(
        Map<String, dynamic> json) =>
    _$CommunityMemberImpl(
      id: json['id'] as String,
      displayName: json['display_name'] as String,
      username: json['username'] as String,
      initials: json['initials'] as String,
      accentColor: json['accent_color'] as String,
      roleLabel: json['role_label'] as String,
    );

Map<String, dynamic> _$$CommunityMemberImplToJson(
        _$CommunityMemberImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'display_name': instance.displayName,
      'username': instance.username,
      'initials': instance.initials,
      'accent_color': instance.accentColor,
      'role_label': instance.roleLabel,
    };

_$CommunityDetailImpl _$$CommunityDetailImplFromJson(
        Map<String, dynamic> json) =>
    _$CommunityDetailImpl(
      community: Community.fromJson(json['community'] as Map<String, dynamic>),
      discussions: (json['discussions'] as List<dynamic>)
          .map((e) => Discussion.fromJson(e as Map<String, dynamic>))
          .toList(),
      members: (json['members'] as List<dynamic>)
          .map((e) => CommunityMember.fromJson(e as Map<String, dynamic>))
          .toList(),
    );

Map<String, dynamic> _$$CommunityDetailImplToJson(
        _$CommunityDetailImpl instance) =>
    <String, dynamic>{
      'community': instance.community.toJson(),
      'discussions': instance.discussions.map((e) => e.toJson()).toList(),
      'members': instance.members.map((e) => e.toJson()).toList(),
    };
