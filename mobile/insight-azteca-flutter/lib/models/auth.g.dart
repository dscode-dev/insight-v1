// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'auth.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$TokensImpl _$$TokensImplFromJson(Map<String, dynamic> json) => _$TokensImpl(
      accessToken: json['access_token'] as String,
      refreshToken: json['refresh_token'] as String,
      userId: json['user_id'] as String?,
      accessExpiresAt: json['access_expires_at'] == null
          ? null
          : DateTime.parse(json['access_expires_at'] as String),
    );

Map<String, dynamic> _$$TokensImplToJson(_$TokensImpl instance) =>
    <String, dynamic>{
      'access_token': instance.accessToken,
      'refresh_token': instance.refreshToken,
      if (instance.userId case final value?) 'user_id': value,
      if (instance.accessExpiresAt?.toIso8601String() case final value?)
        'access_expires_at': value,
    };

_$AuthUserImpl _$$AuthUserImplFromJson(Map<String, dynamic> json) =>
    _$AuthUserImpl(
      id: json['id'] as String,
      username: json['username'] as String,
      displayName: json['display_name'] as String,
      accentColor: json['accent_color'] as String?,
      phoneE164: json['phone_e164'] as String?,
      avatarUrl: json['avatar_url'] as String?,
    );

Map<String, dynamic> _$$AuthUserImplToJson(_$AuthUserImpl instance) =>
    <String, dynamic>{
      'id': instance.id,
      'username': instance.username,
      'display_name': instance.displayName,
      if (instance.accentColor case final value?) 'accent_color': value,
      if (instance.phoneE164 case final value?) 'phone_e164': value,
      if (instance.avatarUrl case final value?) 'avatar_url': value,
    };

_$RequestOtpRequestImpl _$$RequestOtpRequestImplFromJson(
        Map<String, dynamic> json) =>
    _$RequestOtpRequestImpl(
      phone: json['phone'] as String,
    );

Map<String, dynamic> _$$RequestOtpRequestImplToJson(
        _$RequestOtpRequestImpl instance) =>
    <String, dynamic>{
      'phone': instance.phone,
    };

_$VerifyOtpRequestImpl _$$VerifyOtpRequestImplFromJson(
        Map<String, dynamic> json) =>
    _$VerifyOtpRequestImpl(
      phone: json['phone'] as String,
      code: json['code'] as String,
    );

Map<String, dynamic> _$$VerifyOtpRequestImplToJson(
        _$VerifyOtpRequestImpl instance) =>
    <String, dynamic>{
      'phone': instance.phone,
      'code': instance.code,
    };

_$RegistrationHandoffImpl _$$RegistrationHandoffImplFromJson(
        Map<String, dynamic> json) =>
    _$RegistrationHandoffImpl(
      registrationToken: json['registration_token'] as String,
      registrationTtlSeconds: (json['registration_ttl_seconds'] as num).toInt(),
    );

Map<String, dynamic> _$$RegistrationHandoffImplToJson(
        _$RegistrationHandoffImpl instance) =>
    <String, dynamic>{
      'registration_token': instance.registrationToken,
      'registration_ttl_seconds': instance.registrationTtlSeconds,
    };

_$VerifyOtpResponseImpl _$$VerifyOtpResponseImplFromJson(
        Map<String, dynamic> json) =>
    _$VerifyOtpResponseImpl(
      status: json['status'] as String,
      tokens: json['tokens'] == null
          ? null
          : Tokens.fromJson(json['tokens'] as Map<String, dynamic>),
      registration: json['registration'] == null
          ? null
          : RegistrationHandoff.fromJson(
              json['registration'] as Map<String, dynamic>),
      user: json['user'] == null
          ? null
          : AuthUser.fromJson(json['user'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$$VerifyOtpResponseImplToJson(
        _$VerifyOtpResponseImpl instance) =>
    <String, dynamic>{
      'status': instance.status,
      if (instance.tokens?.toJson() case final value?) 'tokens': value,
      if (instance.registration?.toJson() case final value?)
        'registration': value,
      if (instance.user?.toJson() case final value?) 'user': value,
    };

_$CompleteRegistrationRequestImpl _$$CompleteRegistrationRequestImplFromJson(
        Map<String, dynamic> json) =>
    _$CompleteRegistrationRequestImpl(
      registrationToken: json['registration_token'] as String,
      username: json['username'] as String,
      displayName: json['display_name'] as String,
      accentColor: json['accent_color'] as String?,
    );

Map<String, dynamic> _$$CompleteRegistrationRequestImplToJson(
        _$CompleteRegistrationRequestImpl instance) =>
    <String, dynamic>{
      'registration_token': instance.registrationToken,
      'username': instance.username,
      'display_name': instance.displayName,
      if (instance.accentColor case final value?) 'accent_color': value,
    };

_$AuthResponseImpl _$$AuthResponseImplFromJson(Map<String, dynamic> json) =>
    _$AuthResponseImpl(
      tokens: Tokens.fromJson(json['tokens'] as Map<String, dynamic>),
      user: AuthUser.fromJson(json['user'] as Map<String, dynamic>),
    );

Map<String, dynamic> _$$AuthResponseImplToJson(_$AuthResponseImpl instance) =>
    <String, dynamic>{
      'tokens': instance.tokens.toJson(),
      'user': instance.user.toJson(),
    };
