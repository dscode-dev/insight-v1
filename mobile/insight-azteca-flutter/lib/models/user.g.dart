// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'user.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$CurrentUserImpl _$$CurrentUserImplFromJson(Map<String, dynamic> json) =>
    _$CurrentUserImpl(
      id: json['id'] as String,
      username: json['username'] as String,
      displayName: json['display_name'] as String,
      initials: json['initials'] as String,
      accentColor: json['accent_color'] as String,
      reputation: (json['reputation'] as num?)?.toInt(),
      tier: $enumDecodeNullable(_$UserTierEnumMap, json['tier']),
    );

Map<String, dynamic> _$$CurrentUserImplToJson(_$CurrentUserImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'username': instance.username,
      'display_name': instance.displayName,
      'initials': instance.initials,
      'accent_color': instance.accentColor,
      if (instance.reputation case final value?) 'reputation': value,
      if (_$UserTierEnumMap[instance.tier] case final value?) 'tier': value,
    };

const _$UserTierEnumMap = {
  UserTier.rookie: 'rookie',
  UserTier.scout: 'scout',
  UserTier.analyst: 'analyst',
  UserTier.oracle: 'oracle',
};
