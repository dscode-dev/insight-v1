// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'preferences.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$UserPreferencesImpl _$$UserPreferencesImplFromJson(
        Map<String, dynamic> json) =>
    _$UserPreferencesImpl(
      userId: json['user_id'] as String,
      locale: json['locale'] as String,
      pushEnabled: json['push_enabled'] as bool,
      emailEnabled: json['email_enabled'] as bool,
      digestFrequency: json['digest_frequency'] as String,
      updatedAt: DateTime.parse(json['updated_at'] as String),
    );

Map<String, dynamic> _$$UserPreferencesImplToJson(
        _$UserPreferencesImpl instance) =>
    <String, dynamic>{
      'user_id': instance.userId,
      'locale': instance.locale,
      'push_enabled': instance.pushEnabled,
      'email_enabled': instance.emailEnabled,
      'digest_frequency': instance.digestFrequency,
      'updated_at': instance.updatedAt.toIso8601String(),
    };
