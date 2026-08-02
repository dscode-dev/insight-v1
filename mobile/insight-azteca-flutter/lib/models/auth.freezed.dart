// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'auth.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

Tokens _$TokensFromJson(Map<String, dynamic> json) {
  return _Tokens.fromJson(json);
}

/// @nodoc
mixin _$Tokens {
  String get accessToken => throw _privateConstructorUsedError;
  String get refreshToken => throw _privateConstructorUsedError;
  String? get userId => throw _privateConstructorUsedError;
  DateTime? get accessExpiresAt => throw _privateConstructorUsedError;

  /// Serializes this Tokens to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of Tokens
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TokensCopyWith<Tokens> get copyWith => throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TokensCopyWith<$Res> {
  factory $TokensCopyWith(Tokens value, $Res Function(Tokens) then) =
      _$TokensCopyWithImpl<$Res, Tokens>;
  @useResult
  $Res call(
      {String accessToken,
      String refreshToken,
      String? userId,
      DateTime? accessExpiresAt});
}

/// @nodoc
class _$TokensCopyWithImpl<$Res, $Val extends Tokens>
    implements $TokensCopyWith<$Res> {
  _$TokensCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of Tokens
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? accessToken = null,
    Object? refreshToken = null,
    Object? userId = freezed,
    Object? accessExpiresAt = freezed,
  }) {
    return _then(_value.copyWith(
      accessToken: null == accessToken
          ? _value.accessToken
          : accessToken // ignore: cast_nullable_to_non_nullable
              as String,
      refreshToken: null == refreshToken
          ? _value.refreshToken
          : refreshToken // ignore: cast_nullable_to_non_nullable
              as String,
      userId: freezed == userId
          ? _value.userId
          : userId // ignore: cast_nullable_to_non_nullable
              as String?,
      accessExpiresAt: freezed == accessExpiresAt
          ? _value.accessExpiresAt
          : accessExpiresAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$TokensImplCopyWith<$Res> implements $TokensCopyWith<$Res> {
  factory _$$TokensImplCopyWith(
          _$TokensImpl value, $Res Function(_$TokensImpl) then) =
      __$$TokensImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String accessToken,
      String refreshToken,
      String? userId,
      DateTime? accessExpiresAt});
}

/// @nodoc
class __$$TokensImplCopyWithImpl<$Res>
    extends _$TokensCopyWithImpl<$Res, _$TokensImpl>
    implements _$$TokensImplCopyWith<$Res> {
  __$$TokensImplCopyWithImpl(
      _$TokensImpl _value, $Res Function(_$TokensImpl) _then)
      : super(_value, _then);

  /// Create a copy of Tokens
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? accessToken = null,
    Object? refreshToken = null,
    Object? userId = freezed,
    Object? accessExpiresAt = freezed,
  }) {
    return _then(_$TokensImpl(
      accessToken: null == accessToken
          ? _value.accessToken
          : accessToken // ignore: cast_nullable_to_non_nullable
              as String,
      refreshToken: null == refreshToken
          ? _value.refreshToken
          : refreshToken // ignore: cast_nullable_to_non_nullable
              as String,
      userId: freezed == userId
          ? _value.userId
          : userId // ignore: cast_nullable_to_non_nullable
              as String?,
      accessExpiresAt: freezed == accessExpiresAt
          ? _value.accessExpiresAt
          : accessExpiresAt // ignore: cast_nullable_to_non_nullable
              as DateTime?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$TokensImpl implements _Tokens {
  const _$TokensImpl(
      {required this.accessToken,
      required this.refreshToken,
      this.userId,
      this.accessExpiresAt});

  factory _$TokensImpl.fromJson(Map<String, dynamic> json) =>
      _$$TokensImplFromJson(json);

  @override
  final String accessToken;
  @override
  final String refreshToken;
  @override
  final String? userId;
  @override
  final DateTime? accessExpiresAt;

  @override
  String toString() {
    return 'Tokens(accessToken: $accessToken, refreshToken: $refreshToken, userId: $userId, accessExpiresAt: $accessExpiresAt)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TokensImpl &&
            (identical(other.accessToken, accessToken) ||
                other.accessToken == accessToken) &&
            (identical(other.refreshToken, refreshToken) ||
                other.refreshToken == refreshToken) &&
            (identical(other.userId, userId) || other.userId == userId) &&
            (identical(other.accessExpiresAt, accessExpiresAt) ||
                other.accessExpiresAt == accessExpiresAt));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType, accessToken, refreshToken, userId, accessExpiresAt);

  /// Create a copy of Tokens
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TokensImplCopyWith<_$TokensImpl> get copyWith =>
      __$$TokensImplCopyWithImpl<_$TokensImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$TokensImplToJson(
      this,
    );
  }
}

abstract class _Tokens implements Tokens {
  const factory _Tokens(
      {required final String accessToken,
      required final String refreshToken,
      final String? userId,
      final DateTime? accessExpiresAt}) = _$TokensImpl;

  factory _Tokens.fromJson(Map<String, dynamic> json) = _$TokensImpl.fromJson;

  @override
  String get accessToken;
  @override
  String get refreshToken;
  @override
  String? get userId;
  @override
  DateTime? get accessExpiresAt;

  /// Create a copy of Tokens
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TokensImplCopyWith<_$TokensImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

AuthUser _$AuthUserFromJson(Map<String, dynamic> json) {
  return _AuthUser.fromJson(json);
}

/// @nodoc
mixin _$AuthUser {
  String get id => throw _privateConstructorUsedError;
  String get username => throw _privateConstructorUsedError;
  String get displayName => throw _privateConstructorUsedError;
  String? get accentColor => throw _privateConstructorUsedError;
  String? get phoneE164 =>
      throw _privateConstructorUsedError; // Sprint C — full URL of the uploaded avatar. Null means the
// client should render the initials+accent fallback.
  String? get avatarUrl => throw _privateConstructorUsedError;

  /// Serializes this AuthUser to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of AuthUser
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $AuthUserCopyWith<AuthUser> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AuthUserCopyWith<$Res> {
  factory $AuthUserCopyWith(AuthUser value, $Res Function(AuthUser) then) =
      _$AuthUserCopyWithImpl<$Res, AuthUser>;
  @useResult
  $Res call(
      {String id,
      String username,
      String displayName,
      String? accentColor,
      String? phoneE164,
      String? avatarUrl});
}

/// @nodoc
class _$AuthUserCopyWithImpl<$Res, $Val extends AuthUser>
    implements $AuthUserCopyWith<$Res> {
  _$AuthUserCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of AuthUser
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? username = null,
    Object? displayName = null,
    Object? accentColor = freezed,
    Object? phoneE164 = freezed,
    Object? avatarUrl = freezed,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: freezed == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String?,
      phoneE164: freezed == phoneE164
          ? _value.phoneE164
          : phoneE164 // ignore: cast_nullable_to_non_nullable
              as String?,
      avatarUrl: freezed == avatarUrl
          ? _value.avatarUrl
          : avatarUrl // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$AuthUserImplCopyWith<$Res>
    implements $AuthUserCopyWith<$Res> {
  factory _$$AuthUserImplCopyWith(
          _$AuthUserImpl value, $Res Function(_$AuthUserImpl) then) =
      __$$AuthUserImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String username,
      String displayName,
      String? accentColor,
      String? phoneE164,
      String? avatarUrl});
}

/// @nodoc
class __$$AuthUserImplCopyWithImpl<$Res>
    extends _$AuthUserCopyWithImpl<$Res, _$AuthUserImpl>
    implements _$$AuthUserImplCopyWith<$Res> {
  __$$AuthUserImplCopyWithImpl(
      _$AuthUserImpl _value, $Res Function(_$AuthUserImpl) _then)
      : super(_value, _then);

  /// Create a copy of AuthUser
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? username = null,
    Object? displayName = null,
    Object? accentColor = freezed,
    Object? phoneE164 = freezed,
    Object? avatarUrl = freezed,
  }) {
    return _then(_$AuthUserImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: freezed == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String?,
      phoneE164: freezed == phoneE164
          ? _value.phoneE164
          : phoneE164 // ignore: cast_nullable_to_non_nullable
              as String?,
      avatarUrl: freezed == avatarUrl
          ? _value.avatarUrl
          : avatarUrl // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$AuthUserImpl implements _AuthUser {
  const _$AuthUserImpl(
      {required this.id,
      required this.username,
      required this.displayName,
      this.accentColor,
      this.phoneE164,
      this.avatarUrl});

  factory _$AuthUserImpl.fromJson(Map<String, dynamic> json) =>
      _$$AuthUserImplFromJson(json);

  @override
  final String id;
  @override
  final String username;
  @override
  final String displayName;
  @override
  final String? accentColor;
  @override
  final String? phoneE164;
// Sprint C — full URL of the uploaded avatar. Null means the
// client should render the initials+accent fallback.
  @override
  final String? avatarUrl;

  @override
  String toString() {
    return 'AuthUser(id: $id, username: $username, displayName: $displayName, accentColor: $accentColor, phoneE164: $phoneE164, avatarUrl: $avatarUrl)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AuthUserImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.username, username) ||
                other.username == username) &&
            (identical(other.displayName, displayName) ||
                other.displayName == displayName) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor) &&
            (identical(other.phoneE164, phoneE164) ||
                other.phoneE164 == phoneE164) &&
            (identical(other.avatarUrl, avatarUrl) ||
                other.avatarUrl == avatarUrl));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, username, displayName,
      accentColor, phoneE164, avatarUrl);

  /// Create a copy of AuthUser
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$AuthUserImplCopyWith<_$AuthUserImpl> get copyWith =>
      __$$AuthUserImplCopyWithImpl<_$AuthUserImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AuthUserImplToJson(
      this,
    );
  }
}

abstract class _AuthUser implements AuthUser {
  const factory _AuthUser(
      {required final String id,
      required final String username,
      required final String displayName,
      final String? accentColor,
      final String? phoneE164,
      final String? avatarUrl}) = _$AuthUserImpl;

  factory _AuthUser.fromJson(Map<String, dynamic> json) =
      _$AuthUserImpl.fromJson;

  @override
  String get id;
  @override
  String get username;
  @override
  String get displayName;
  @override
  String? get accentColor;
  @override
  String?
      get phoneE164; // Sprint C — full URL of the uploaded avatar. Null means the
// client should render the initials+accent fallback.
  @override
  String? get avatarUrl;

  /// Create a copy of AuthUser
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$AuthUserImplCopyWith<_$AuthUserImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

RequestOtpRequest _$RequestOtpRequestFromJson(Map<String, dynamic> json) {
  return _RequestOtpRequest.fromJson(json);
}

/// @nodoc
mixin _$RequestOtpRequest {
  String get phone => throw _privateConstructorUsedError;

  /// Serializes this RequestOtpRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of RequestOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $RequestOtpRequestCopyWith<RequestOtpRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $RequestOtpRequestCopyWith<$Res> {
  factory $RequestOtpRequestCopyWith(
          RequestOtpRequest value, $Res Function(RequestOtpRequest) then) =
      _$RequestOtpRequestCopyWithImpl<$Res, RequestOtpRequest>;
  @useResult
  $Res call({String phone});
}

/// @nodoc
class _$RequestOtpRequestCopyWithImpl<$Res, $Val extends RequestOtpRequest>
    implements $RequestOtpRequestCopyWith<$Res> {
  _$RequestOtpRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of RequestOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? phone = null,
  }) {
    return _then(_value.copyWith(
      phone: null == phone
          ? _value.phone
          : phone // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$RequestOtpRequestImplCopyWith<$Res>
    implements $RequestOtpRequestCopyWith<$Res> {
  factory _$$RequestOtpRequestImplCopyWith(_$RequestOtpRequestImpl value,
          $Res Function(_$RequestOtpRequestImpl) then) =
      __$$RequestOtpRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String phone});
}

/// @nodoc
class __$$RequestOtpRequestImplCopyWithImpl<$Res>
    extends _$RequestOtpRequestCopyWithImpl<$Res, _$RequestOtpRequestImpl>
    implements _$$RequestOtpRequestImplCopyWith<$Res> {
  __$$RequestOtpRequestImplCopyWithImpl(_$RequestOtpRequestImpl _value,
      $Res Function(_$RequestOtpRequestImpl) _then)
      : super(_value, _then);

  /// Create a copy of RequestOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? phone = null,
  }) {
    return _then(_$RequestOtpRequestImpl(
      phone: null == phone
          ? _value.phone
          : phone // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$RequestOtpRequestImpl implements _RequestOtpRequest {
  const _$RequestOtpRequestImpl({required this.phone});

  factory _$RequestOtpRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$RequestOtpRequestImplFromJson(json);

  @override
  final String phone;

  @override
  String toString() {
    return 'RequestOtpRequest(phone: $phone)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$RequestOtpRequestImpl &&
            (identical(other.phone, phone) || other.phone == phone));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, phone);

  /// Create a copy of RequestOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$RequestOtpRequestImplCopyWith<_$RequestOtpRequestImpl> get copyWith =>
      __$$RequestOtpRequestImplCopyWithImpl<_$RequestOtpRequestImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$RequestOtpRequestImplToJson(
      this,
    );
  }
}

abstract class _RequestOtpRequest implements RequestOtpRequest {
  const factory _RequestOtpRequest({required final String phone}) =
      _$RequestOtpRequestImpl;

  factory _RequestOtpRequest.fromJson(Map<String, dynamic> json) =
      _$RequestOtpRequestImpl.fromJson;

  @override
  String get phone;

  /// Create a copy of RequestOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$RequestOtpRequestImplCopyWith<_$RequestOtpRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

VerifyOtpRequest _$VerifyOtpRequestFromJson(Map<String, dynamic> json) {
  return _VerifyOtpRequest.fromJson(json);
}

/// @nodoc
mixin _$VerifyOtpRequest {
  String get phone => throw _privateConstructorUsedError;
  String get code => throw _privateConstructorUsedError;

  /// Serializes this VerifyOtpRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of VerifyOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $VerifyOtpRequestCopyWith<VerifyOtpRequest> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $VerifyOtpRequestCopyWith<$Res> {
  factory $VerifyOtpRequestCopyWith(
          VerifyOtpRequest value, $Res Function(VerifyOtpRequest) then) =
      _$VerifyOtpRequestCopyWithImpl<$Res, VerifyOtpRequest>;
  @useResult
  $Res call({String phone, String code});
}

/// @nodoc
class _$VerifyOtpRequestCopyWithImpl<$Res, $Val extends VerifyOtpRequest>
    implements $VerifyOtpRequestCopyWith<$Res> {
  _$VerifyOtpRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of VerifyOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? phone = null,
    Object? code = null,
  }) {
    return _then(_value.copyWith(
      phone: null == phone
          ? _value.phone
          : phone // ignore: cast_nullable_to_non_nullable
              as String,
      code: null == code
          ? _value.code
          : code // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$VerifyOtpRequestImplCopyWith<$Res>
    implements $VerifyOtpRequestCopyWith<$Res> {
  factory _$$VerifyOtpRequestImplCopyWith(_$VerifyOtpRequestImpl value,
          $Res Function(_$VerifyOtpRequestImpl) then) =
      __$$VerifyOtpRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String phone, String code});
}

/// @nodoc
class __$$VerifyOtpRequestImplCopyWithImpl<$Res>
    extends _$VerifyOtpRequestCopyWithImpl<$Res, _$VerifyOtpRequestImpl>
    implements _$$VerifyOtpRequestImplCopyWith<$Res> {
  __$$VerifyOtpRequestImplCopyWithImpl(_$VerifyOtpRequestImpl _value,
      $Res Function(_$VerifyOtpRequestImpl) _then)
      : super(_value, _then);

  /// Create a copy of VerifyOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? phone = null,
    Object? code = null,
  }) {
    return _then(_$VerifyOtpRequestImpl(
      phone: null == phone
          ? _value.phone
          : phone // ignore: cast_nullable_to_non_nullable
              as String,
      code: null == code
          ? _value.code
          : code // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$VerifyOtpRequestImpl implements _VerifyOtpRequest {
  const _$VerifyOtpRequestImpl({required this.phone, required this.code});

  factory _$VerifyOtpRequestImpl.fromJson(Map<String, dynamic> json) =>
      _$$VerifyOtpRequestImplFromJson(json);

  @override
  final String phone;
  @override
  final String code;

  @override
  String toString() {
    return 'VerifyOtpRequest(phone: $phone, code: $code)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$VerifyOtpRequestImpl &&
            (identical(other.phone, phone) || other.phone == phone) &&
            (identical(other.code, code) || other.code == code));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, phone, code);

  /// Create a copy of VerifyOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$VerifyOtpRequestImplCopyWith<_$VerifyOtpRequestImpl> get copyWith =>
      __$$VerifyOtpRequestImplCopyWithImpl<_$VerifyOtpRequestImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$VerifyOtpRequestImplToJson(
      this,
    );
  }
}

abstract class _VerifyOtpRequest implements VerifyOtpRequest {
  const factory _VerifyOtpRequest(
      {required final String phone,
      required final String code}) = _$VerifyOtpRequestImpl;

  factory _VerifyOtpRequest.fromJson(Map<String, dynamic> json) =
      _$VerifyOtpRequestImpl.fromJson;

  @override
  String get phone;
  @override
  String get code;

  /// Create a copy of VerifyOtpRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$VerifyOtpRequestImplCopyWith<_$VerifyOtpRequestImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

RegistrationHandoff _$RegistrationHandoffFromJson(Map<String, dynamic> json) {
  return _RegistrationHandoff.fromJson(json);
}

/// @nodoc
mixin _$RegistrationHandoff {
  String get registrationToken => throw _privateConstructorUsedError;
  int get registrationTtlSeconds => throw _privateConstructorUsedError;

  /// Serializes this RegistrationHandoff to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of RegistrationHandoff
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $RegistrationHandoffCopyWith<RegistrationHandoff> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $RegistrationHandoffCopyWith<$Res> {
  factory $RegistrationHandoffCopyWith(
          RegistrationHandoff value, $Res Function(RegistrationHandoff) then) =
      _$RegistrationHandoffCopyWithImpl<$Res, RegistrationHandoff>;
  @useResult
  $Res call({String registrationToken, int registrationTtlSeconds});
}

/// @nodoc
class _$RegistrationHandoffCopyWithImpl<$Res, $Val extends RegistrationHandoff>
    implements $RegistrationHandoffCopyWith<$Res> {
  _$RegistrationHandoffCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of RegistrationHandoff
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? registrationToken = null,
    Object? registrationTtlSeconds = null,
  }) {
    return _then(_value.copyWith(
      registrationToken: null == registrationToken
          ? _value.registrationToken
          : registrationToken // ignore: cast_nullable_to_non_nullable
              as String,
      registrationTtlSeconds: null == registrationTtlSeconds
          ? _value.registrationTtlSeconds
          : registrationTtlSeconds // ignore: cast_nullable_to_non_nullable
              as int,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$RegistrationHandoffImplCopyWith<$Res>
    implements $RegistrationHandoffCopyWith<$Res> {
  factory _$$RegistrationHandoffImplCopyWith(_$RegistrationHandoffImpl value,
          $Res Function(_$RegistrationHandoffImpl) then) =
      __$$RegistrationHandoffImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String registrationToken, int registrationTtlSeconds});
}

/// @nodoc
class __$$RegistrationHandoffImplCopyWithImpl<$Res>
    extends _$RegistrationHandoffCopyWithImpl<$Res, _$RegistrationHandoffImpl>
    implements _$$RegistrationHandoffImplCopyWith<$Res> {
  __$$RegistrationHandoffImplCopyWithImpl(_$RegistrationHandoffImpl _value,
      $Res Function(_$RegistrationHandoffImpl) _then)
      : super(_value, _then);

  /// Create a copy of RegistrationHandoff
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? registrationToken = null,
    Object? registrationTtlSeconds = null,
  }) {
    return _then(_$RegistrationHandoffImpl(
      registrationToken: null == registrationToken
          ? _value.registrationToken
          : registrationToken // ignore: cast_nullable_to_non_nullable
              as String,
      registrationTtlSeconds: null == registrationTtlSeconds
          ? _value.registrationTtlSeconds
          : registrationTtlSeconds // ignore: cast_nullable_to_non_nullable
              as int,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$RegistrationHandoffImpl implements _RegistrationHandoff {
  const _$RegistrationHandoffImpl(
      {required this.registrationToken, required this.registrationTtlSeconds});

  factory _$RegistrationHandoffImpl.fromJson(Map<String, dynamic> json) =>
      _$$RegistrationHandoffImplFromJson(json);

  @override
  final String registrationToken;
  @override
  final int registrationTtlSeconds;

  @override
  String toString() {
    return 'RegistrationHandoff(registrationToken: $registrationToken, registrationTtlSeconds: $registrationTtlSeconds)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$RegistrationHandoffImpl &&
            (identical(other.registrationToken, registrationToken) ||
                other.registrationToken == registrationToken) &&
            (identical(other.registrationTtlSeconds, registrationTtlSeconds) ||
                other.registrationTtlSeconds == registrationTtlSeconds));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, registrationToken, registrationTtlSeconds);

  /// Create a copy of RegistrationHandoff
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$RegistrationHandoffImplCopyWith<_$RegistrationHandoffImpl> get copyWith =>
      __$$RegistrationHandoffImplCopyWithImpl<_$RegistrationHandoffImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$RegistrationHandoffImplToJson(
      this,
    );
  }
}

abstract class _RegistrationHandoff implements RegistrationHandoff {
  const factory _RegistrationHandoff(
      {required final String registrationToken,
      required final int registrationTtlSeconds}) = _$RegistrationHandoffImpl;

  factory _RegistrationHandoff.fromJson(Map<String, dynamic> json) =
      _$RegistrationHandoffImpl.fromJson;

  @override
  String get registrationToken;
  @override
  int get registrationTtlSeconds;

  /// Create a copy of RegistrationHandoff
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$RegistrationHandoffImplCopyWith<_$RegistrationHandoffImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

VerifyOtpResponse _$VerifyOtpResponseFromJson(Map<String, dynamic> json) {
  return _VerifyOtpResponse.fromJson(json);
}

/// @nodoc
mixin _$VerifyOtpResponse {
  String get status => throw _privateConstructorUsedError;
  Tokens? get tokens => throw _privateConstructorUsedError;
  RegistrationHandoff? get registration => throw _privateConstructorUsedError;
  AuthUser? get user => throw _privateConstructorUsedError;

  /// Serializes this VerifyOtpResponse to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $VerifyOtpResponseCopyWith<VerifyOtpResponse> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $VerifyOtpResponseCopyWith<$Res> {
  factory $VerifyOtpResponseCopyWith(
          VerifyOtpResponse value, $Res Function(VerifyOtpResponse) then) =
      _$VerifyOtpResponseCopyWithImpl<$Res, VerifyOtpResponse>;
  @useResult
  $Res call(
      {String status,
      Tokens? tokens,
      RegistrationHandoff? registration,
      AuthUser? user});

  $TokensCopyWith<$Res>? get tokens;
  $RegistrationHandoffCopyWith<$Res>? get registration;
  $AuthUserCopyWith<$Res>? get user;
}

/// @nodoc
class _$VerifyOtpResponseCopyWithImpl<$Res, $Val extends VerifyOtpResponse>
    implements $VerifyOtpResponseCopyWith<$Res> {
  _$VerifyOtpResponseCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? status = null,
    Object? tokens = freezed,
    Object? registration = freezed,
    Object? user = freezed,
  }) {
    return _then(_value.copyWith(
      status: null == status
          ? _value.status
          : status // ignore: cast_nullable_to_non_nullable
              as String,
      tokens: freezed == tokens
          ? _value.tokens
          : tokens // ignore: cast_nullable_to_non_nullable
              as Tokens?,
      registration: freezed == registration
          ? _value.registration
          : registration // ignore: cast_nullable_to_non_nullable
              as RegistrationHandoff?,
      user: freezed == user
          ? _value.user
          : user // ignore: cast_nullable_to_non_nullable
              as AuthUser?,
    ) as $Val);
  }

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $TokensCopyWith<$Res>? get tokens {
    if (_value.tokens == null) {
      return null;
    }

    return $TokensCopyWith<$Res>(_value.tokens!, (value) {
      return _then(_value.copyWith(tokens: value) as $Val);
    });
  }

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $RegistrationHandoffCopyWith<$Res>? get registration {
    if (_value.registration == null) {
      return null;
    }

    return $RegistrationHandoffCopyWith<$Res>(_value.registration!, (value) {
      return _then(_value.copyWith(registration: value) as $Val);
    });
  }

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $AuthUserCopyWith<$Res>? get user {
    if (_value.user == null) {
      return null;
    }

    return $AuthUserCopyWith<$Res>(_value.user!, (value) {
      return _then(_value.copyWith(user: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$VerifyOtpResponseImplCopyWith<$Res>
    implements $VerifyOtpResponseCopyWith<$Res> {
  factory _$$VerifyOtpResponseImplCopyWith(_$VerifyOtpResponseImpl value,
          $Res Function(_$VerifyOtpResponseImpl) then) =
      __$$VerifyOtpResponseImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String status,
      Tokens? tokens,
      RegistrationHandoff? registration,
      AuthUser? user});

  @override
  $TokensCopyWith<$Res>? get tokens;
  @override
  $RegistrationHandoffCopyWith<$Res>? get registration;
  @override
  $AuthUserCopyWith<$Res>? get user;
}

/// @nodoc
class __$$VerifyOtpResponseImplCopyWithImpl<$Res>
    extends _$VerifyOtpResponseCopyWithImpl<$Res, _$VerifyOtpResponseImpl>
    implements _$$VerifyOtpResponseImplCopyWith<$Res> {
  __$$VerifyOtpResponseImplCopyWithImpl(_$VerifyOtpResponseImpl _value,
      $Res Function(_$VerifyOtpResponseImpl) _then)
      : super(_value, _then);

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? status = null,
    Object? tokens = freezed,
    Object? registration = freezed,
    Object? user = freezed,
  }) {
    return _then(_$VerifyOtpResponseImpl(
      status: null == status
          ? _value.status
          : status // ignore: cast_nullable_to_non_nullable
              as String,
      tokens: freezed == tokens
          ? _value.tokens
          : tokens // ignore: cast_nullable_to_non_nullable
              as Tokens?,
      registration: freezed == registration
          ? _value.registration
          : registration // ignore: cast_nullable_to_non_nullable
              as RegistrationHandoff?,
      user: freezed == user
          ? _value.user
          : user // ignore: cast_nullable_to_non_nullable
              as AuthUser?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$VerifyOtpResponseImpl implements _VerifyOtpResponse {
  const _$VerifyOtpResponseImpl(
      {required this.status, this.tokens, this.registration, this.user});

  factory _$VerifyOtpResponseImpl.fromJson(Map<String, dynamic> json) =>
      _$$VerifyOtpResponseImplFromJson(json);

  @override
  final String status;
  @override
  final Tokens? tokens;
  @override
  final RegistrationHandoff? registration;
  @override
  final AuthUser? user;

  @override
  String toString() {
    return 'VerifyOtpResponse(status: $status, tokens: $tokens, registration: $registration, user: $user)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$VerifyOtpResponseImpl &&
            (identical(other.status, status) || other.status == status) &&
            (identical(other.tokens, tokens) || other.tokens == tokens) &&
            (identical(other.registration, registration) ||
                other.registration == registration) &&
            (identical(other.user, user) || other.user == user));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, status, tokens, registration, user);

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$VerifyOtpResponseImplCopyWith<_$VerifyOtpResponseImpl> get copyWith =>
      __$$VerifyOtpResponseImplCopyWithImpl<_$VerifyOtpResponseImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$VerifyOtpResponseImplToJson(
      this,
    );
  }
}

abstract class _VerifyOtpResponse implements VerifyOtpResponse {
  const factory _VerifyOtpResponse(
      {required final String status,
      final Tokens? tokens,
      final RegistrationHandoff? registration,
      final AuthUser? user}) = _$VerifyOtpResponseImpl;

  factory _VerifyOtpResponse.fromJson(Map<String, dynamic> json) =
      _$VerifyOtpResponseImpl.fromJson;

  @override
  String get status;
  @override
  Tokens? get tokens;
  @override
  RegistrationHandoff? get registration;
  @override
  AuthUser? get user;

  /// Create a copy of VerifyOtpResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$VerifyOtpResponseImplCopyWith<_$VerifyOtpResponseImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

CompleteRegistrationRequest _$CompleteRegistrationRequestFromJson(
    Map<String, dynamic> json) {
  return _CompleteRegistrationRequest.fromJson(json);
}

/// @nodoc
mixin _$CompleteRegistrationRequest {
  String get registrationToken => throw _privateConstructorUsedError;
  String get username => throw _privateConstructorUsedError;
  String get displayName => throw _privateConstructorUsedError;
  String? get accentColor => throw _privateConstructorUsedError;

  /// Serializes this CompleteRegistrationRequest to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of CompleteRegistrationRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CompleteRegistrationRequestCopyWith<CompleteRegistrationRequest>
      get copyWith => throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CompleteRegistrationRequestCopyWith<$Res> {
  factory $CompleteRegistrationRequestCopyWith(
          CompleteRegistrationRequest value,
          $Res Function(CompleteRegistrationRequest) then) =
      _$CompleteRegistrationRequestCopyWithImpl<$Res,
          CompleteRegistrationRequest>;
  @useResult
  $Res call(
      {String registrationToken,
      String username,
      String displayName,
      String? accentColor});
}

/// @nodoc
class _$CompleteRegistrationRequestCopyWithImpl<$Res,
        $Val extends CompleteRegistrationRequest>
    implements $CompleteRegistrationRequestCopyWith<$Res> {
  _$CompleteRegistrationRequestCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of CompleteRegistrationRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? registrationToken = null,
    Object? username = null,
    Object? displayName = null,
    Object? accentColor = freezed,
  }) {
    return _then(_value.copyWith(
      registrationToken: null == registrationToken
          ? _value.registrationToken
          : registrationToken // ignore: cast_nullable_to_non_nullable
              as String,
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: freezed == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CompleteRegistrationRequestImplCopyWith<$Res>
    implements $CompleteRegistrationRequestCopyWith<$Res> {
  factory _$$CompleteRegistrationRequestImplCopyWith(
          _$CompleteRegistrationRequestImpl value,
          $Res Function(_$CompleteRegistrationRequestImpl) then) =
      __$$CompleteRegistrationRequestImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String registrationToken,
      String username,
      String displayName,
      String? accentColor});
}

/// @nodoc
class __$$CompleteRegistrationRequestImplCopyWithImpl<$Res>
    extends _$CompleteRegistrationRequestCopyWithImpl<$Res,
        _$CompleteRegistrationRequestImpl>
    implements _$$CompleteRegistrationRequestImplCopyWith<$Res> {
  __$$CompleteRegistrationRequestImplCopyWithImpl(
      _$CompleteRegistrationRequestImpl _value,
      $Res Function(_$CompleteRegistrationRequestImpl) _then)
      : super(_value, _then);

  /// Create a copy of CompleteRegistrationRequest
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? registrationToken = null,
    Object? username = null,
    Object? displayName = null,
    Object? accentColor = freezed,
  }) {
    return _then(_$CompleteRegistrationRequestImpl(
      registrationToken: null == registrationToken
          ? _value.registrationToken
          : registrationToken // ignore: cast_nullable_to_non_nullable
              as String,
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: freezed == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$CompleteRegistrationRequestImpl
    implements _CompleteRegistrationRequest {
  const _$CompleteRegistrationRequestImpl(
      {required this.registrationToken,
      required this.username,
      required this.displayName,
      this.accentColor});

  factory _$CompleteRegistrationRequestImpl.fromJson(
          Map<String, dynamic> json) =>
      _$$CompleteRegistrationRequestImplFromJson(json);

  @override
  final String registrationToken;
  @override
  final String username;
  @override
  final String displayName;
  @override
  final String? accentColor;

  @override
  String toString() {
    return 'CompleteRegistrationRequest(registrationToken: $registrationToken, username: $username, displayName: $displayName, accentColor: $accentColor)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CompleteRegistrationRequestImpl &&
            (identical(other.registrationToken, registrationToken) ||
                other.registrationToken == registrationToken) &&
            (identical(other.username, username) ||
                other.username == username) &&
            (identical(other.displayName, displayName) ||
                other.displayName == displayName) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType, registrationToken, username, displayName, accentColor);

  /// Create a copy of CompleteRegistrationRequest
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CompleteRegistrationRequestImplCopyWith<_$CompleteRegistrationRequestImpl>
      get copyWith => __$$CompleteRegistrationRequestImplCopyWithImpl<
          _$CompleteRegistrationRequestImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CompleteRegistrationRequestImplToJson(
      this,
    );
  }
}

abstract class _CompleteRegistrationRequest
    implements CompleteRegistrationRequest {
  const factory _CompleteRegistrationRequest(
      {required final String registrationToken,
      required final String username,
      required final String displayName,
      final String? accentColor}) = _$CompleteRegistrationRequestImpl;

  factory _CompleteRegistrationRequest.fromJson(Map<String, dynamic> json) =
      _$CompleteRegistrationRequestImpl.fromJson;

  @override
  String get registrationToken;
  @override
  String get username;
  @override
  String get displayName;
  @override
  String? get accentColor;

  /// Create a copy of CompleteRegistrationRequest
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CompleteRegistrationRequestImplCopyWith<_$CompleteRegistrationRequestImpl>
      get copyWith => throw _privateConstructorUsedError;
}

AuthResponse _$AuthResponseFromJson(Map<String, dynamic> json) {
  return _AuthResponse.fromJson(json);
}

/// @nodoc
mixin _$AuthResponse {
  Tokens get tokens => throw _privateConstructorUsedError;
  AuthUser get user => throw _privateConstructorUsedError;

  /// Serializes this AuthResponse to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $AuthResponseCopyWith<AuthResponse> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AuthResponseCopyWith<$Res> {
  factory $AuthResponseCopyWith(
          AuthResponse value, $Res Function(AuthResponse) then) =
      _$AuthResponseCopyWithImpl<$Res, AuthResponse>;
  @useResult
  $Res call({Tokens tokens, AuthUser user});

  $TokensCopyWith<$Res> get tokens;
  $AuthUserCopyWith<$Res> get user;
}

/// @nodoc
class _$AuthResponseCopyWithImpl<$Res, $Val extends AuthResponse>
    implements $AuthResponseCopyWith<$Res> {
  _$AuthResponseCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? tokens = null,
    Object? user = null,
  }) {
    return _then(_value.copyWith(
      tokens: null == tokens
          ? _value.tokens
          : tokens // ignore: cast_nullable_to_non_nullable
              as Tokens,
      user: null == user
          ? _value.user
          : user // ignore: cast_nullable_to_non_nullable
              as AuthUser,
    ) as $Val);
  }

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $TokensCopyWith<$Res> get tokens {
    return $TokensCopyWith<$Res>(_value.tokens, (value) {
      return _then(_value.copyWith(tokens: value) as $Val);
    });
  }

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $AuthUserCopyWith<$Res> get user {
    return $AuthUserCopyWith<$Res>(_value.user, (value) {
      return _then(_value.copyWith(user: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$AuthResponseImplCopyWith<$Res>
    implements $AuthResponseCopyWith<$Res> {
  factory _$$AuthResponseImplCopyWith(
          _$AuthResponseImpl value, $Res Function(_$AuthResponseImpl) then) =
      __$$AuthResponseImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({Tokens tokens, AuthUser user});

  @override
  $TokensCopyWith<$Res> get tokens;
  @override
  $AuthUserCopyWith<$Res> get user;
}

/// @nodoc
class __$$AuthResponseImplCopyWithImpl<$Res>
    extends _$AuthResponseCopyWithImpl<$Res, _$AuthResponseImpl>
    implements _$$AuthResponseImplCopyWith<$Res> {
  __$$AuthResponseImplCopyWithImpl(
      _$AuthResponseImpl _value, $Res Function(_$AuthResponseImpl) _then)
      : super(_value, _then);

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? tokens = null,
    Object? user = null,
  }) {
    return _then(_$AuthResponseImpl(
      tokens: null == tokens
          ? _value.tokens
          : tokens // ignore: cast_nullable_to_non_nullable
              as Tokens,
      user: null == user
          ? _value.user
          : user // ignore: cast_nullable_to_non_nullable
              as AuthUser,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$AuthResponseImpl implements _AuthResponse {
  const _$AuthResponseImpl({required this.tokens, required this.user});

  factory _$AuthResponseImpl.fromJson(Map<String, dynamic> json) =>
      _$$AuthResponseImplFromJson(json);

  @override
  final Tokens tokens;
  @override
  final AuthUser user;

  @override
  String toString() {
    return 'AuthResponse(tokens: $tokens, user: $user)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AuthResponseImpl &&
            (identical(other.tokens, tokens) || other.tokens == tokens) &&
            (identical(other.user, user) || other.user == user));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, tokens, user);

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$AuthResponseImplCopyWith<_$AuthResponseImpl> get copyWith =>
      __$$AuthResponseImplCopyWithImpl<_$AuthResponseImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AuthResponseImplToJson(
      this,
    );
  }
}

abstract class _AuthResponse implements AuthResponse {
  const factory _AuthResponse(
      {required final Tokens tokens,
      required final AuthUser user}) = _$AuthResponseImpl;

  factory _AuthResponse.fromJson(Map<String, dynamic> json) =
      _$AuthResponseImpl.fromJson;

  @override
  Tokens get tokens;
  @override
  AuthUser get user;

  /// Create a copy of AuthResponse
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$AuthResponseImplCopyWith<_$AuthResponseImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
