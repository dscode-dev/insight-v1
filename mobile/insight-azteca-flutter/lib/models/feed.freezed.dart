// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'feed.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

SignalBadgeData _$SignalBadgeDataFromJson(Map<String, dynamic> json) {
  return _SignalBadgeData.fromJson(json);
}

/// @nodoc
mixin _$SignalBadgeData {
  String get label => throw _privateConstructorUsedError;
  SignalBadgeTone get tone => throw _privateConstructorUsedError;

  /// Serializes this SignalBadgeData to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of SignalBadgeData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $SignalBadgeDataCopyWith<SignalBadgeData> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $SignalBadgeDataCopyWith<$Res> {
  factory $SignalBadgeDataCopyWith(
          SignalBadgeData value, $Res Function(SignalBadgeData) then) =
      _$SignalBadgeDataCopyWithImpl<$Res, SignalBadgeData>;
  @useResult
  $Res call({String label, SignalBadgeTone tone});
}

/// @nodoc
class _$SignalBadgeDataCopyWithImpl<$Res, $Val extends SignalBadgeData>
    implements $SignalBadgeDataCopyWith<$Res> {
  _$SignalBadgeDataCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of SignalBadgeData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? label = null,
    Object? tone = null,
  }) {
    return _then(_value.copyWith(
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      tone: null == tone
          ? _value.tone
          : tone // ignore: cast_nullable_to_non_nullable
              as SignalBadgeTone,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$SignalBadgeDataImplCopyWith<$Res>
    implements $SignalBadgeDataCopyWith<$Res> {
  factory _$$SignalBadgeDataImplCopyWith(_$SignalBadgeDataImpl value,
          $Res Function(_$SignalBadgeDataImpl) then) =
      __$$SignalBadgeDataImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String label, SignalBadgeTone tone});
}

/// @nodoc
class __$$SignalBadgeDataImplCopyWithImpl<$Res>
    extends _$SignalBadgeDataCopyWithImpl<$Res, _$SignalBadgeDataImpl>
    implements _$$SignalBadgeDataImplCopyWith<$Res> {
  __$$SignalBadgeDataImplCopyWithImpl(
      _$SignalBadgeDataImpl _value, $Res Function(_$SignalBadgeDataImpl) _then)
      : super(_value, _then);

  /// Create a copy of SignalBadgeData
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? label = null,
    Object? tone = null,
  }) {
    return _then(_$SignalBadgeDataImpl(
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      tone: null == tone
          ? _value.tone
          : tone // ignore: cast_nullable_to_non_nullable
              as SignalBadgeTone,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$SignalBadgeDataImpl implements _SignalBadgeData {
  const _$SignalBadgeDataImpl({required this.label, required this.tone});

  factory _$SignalBadgeDataImpl.fromJson(Map<String, dynamic> json) =>
      _$$SignalBadgeDataImplFromJson(json);

  @override
  final String label;
  @override
  final SignalBadgeTone tone;

  @override
  String toString() {
    return 'SignalBadgeData(label: $label, tone: $tone)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$SignalBadgeDataImpl &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.tone, tone) || other.tone == tone));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, label, tone);

  /// Create a copy of SignalBadgeData
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$SignalBadgeDataImplCopyWith<_$SignalBadgeDataImpl> get copyWith =>
      __$$SignalBadgeDataImplCopyWithImpl<_$SignalBadgeDataImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$SignalBadgeDataImplToJson(
      this,
    );
  }
}

abstract class _SignalBadgeData implements SignalBadgeData {
  const factory _SignalBadgeData(
      {required final String label,
      required final SignalBadgeTone tone}) = _$SignalBadgeDataImpl;

  factory _SignalBadgeData.fromJson(Map<String, dynamic> json) =
      _$SignalBadgeDataImpl.fromJson;

  @override
  String get label;
  @override
  SignalBadgeTone get tone;

  /// Create a copy of SignalBadgeData
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$SignalBadgeDataImplCopyWith<_$SignalBadgeDataImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedAuthor _$FeedAuthorFromJson(Map<String, dynamic> json) {
  return _FeedAuthor.fromJson(json);
}

/// @nodoc
mixin _$FeedAuthor {
  String get id => throw _privateConstructorUsedError;
  String get displayName => throw _privateConstructorUsedError;
  String? get username => throw _privateConstructorUsedError;
  String get initials => throw _privateConstructorUsedError;
  String get accentColor => throw _privateConstructorUsedError;
  bool get isSystem => throw _privateConstructorUsedError;
  int? get reputation => throw _privateConstructorUsedError;
  String? get tier => throw _privateConstructorUsedError;

  /// Serializes this FeedAuthor to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedAuthor
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedAuthorCopyWith<FeedAuthor> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedAuthorCopyWith<$Res> {
  factory $FeedAuthorCopyWith(
          FeedAuthor value, $Res Function(FeedAuthor) then) =
      _$FeedAuthorCopyWithImpl<$Res, FeedAuthor>;
  @useResult
  $Res call(
      {String id,
      String displayName,
      String? username,
      String initials,
      String accentColor,
      bool isSystem,
      int? reputation,
      String? tier});
}

/// @nodoc
class _$FeedAuthorCopyWithImpl<$Res, $Val extends FeedAuthor>
    implements $FeedAuthorCopyWith<$Res> {
  _$FeedAuthorCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedAuthor
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? displayName = null,
    Object? username = freezed,
    Object? initials = null,
    Object? accentColor = null,
    Object? isSystem = null,
    Object? reputation = freezed,
    Object? tier = freezed,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      username: freezed == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String?,
      initials: null == initials
          ? _value.initials
          : initials // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      isSystem: null == isSystem
          ? _value.isSystem
          : isSystem // ignore: cast_nullable_to_non_nullable
              as bool,
      reputation: freezed == reputation
          ? _value.reputation
          : reputation // ignore: cast_nullable_to_non_nullable
              as int?,
      tier: freezed == tier
          ? _value.tier
          : tier // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedAuthorImplCopyWith<$Res>
    implements $FeedAuthorCopyWith<$Res> {
  factory _$$FeedAuthorImplCopyWith(
          _$FeedAuthorImpl value, $Res Function(_$FeedAuthorImpl) then) =
      __$$FeedAuthorImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String displayName,
      String? username,
      String initials,
      String accentColor,
      bool isSystem,
      int? reputation,
      String? tier});
}

/// @nodoc
class __$$FeedAuthorImplCopyWithImpl<$Res>
    extends _$FeedAuthorCopyWithImpl<$Res, _$FeedAuthorImpl>
    implements _$$FeedAuthorImplCopyWith<$Res> {
  __$$FeedAuthorImplCopyWithImpl(
      _$FeedAuthorImpl _value, $Res Function(_$FeedAuthorImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedAuthor
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? displayName = null,
    Object? username = freezed,
    Object? initials = null,
    Object? accentColor = null,
    Object? isSystem = null,
    Object? reputation = freezed,
    Object? tier = freezed,
  }) {
    return _then(_$FeedAuthorImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      username: freezed == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String?,
      initials: null == initials
          ? _value.initials
          : initials // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      isSystem: null == isSystem
          ? _value.isSystem
          : isSystem // ignore: cast_nullable_to_non_nullable
              as bool,
      reputation: freezed == reputation
          ? _value.reputation
          : reputation // ignore: cast_nullable_to_non_nullable
              as int?,
      tier: freezed == tier
          ? _value.tier
          : tier // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedAuthorImpl implements _FeedAuthor {
  const _$FeedAuthorImpl(
      {required this.id,
      required this.displayName,
      this.username,
      required this.initials,
      required this.accentColor,
      required this.isSystem,
      this.reputation,
      this.tier});

  factory _$FeedAuthorImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedAuthorImplFromJson(json);

  @override
  final String id;
  @override
  final String displayName;
  @override
  final String? username;
  @override
  final String initials;
  @override
  final String accentColor;
  @override
  final bool isSystem;
  @override
  final int? reputation;
  @override
  final String? tier;

  @override
  String toString() {
    return 'FeedAuthor(id: $id, displayName: $displayName, username: $username, initials: $initials, accentColor: $accentColor, isSystem: $isSystem, reputation: $reputation, tier: $tier)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedAuthorImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.displayName, displayName) ||
                other.displayName == displayName) &&
            (identical(other.username, username) ||
                other.username == username) &&
            (identical(other.initials, initials) ||
                other.initials == initials) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor) &&
            (identical(other.isSystem, isSystem) ||
                other.isSystem == isSystem) &&
            (identical(other.reputation, reputation) ||
                other.reputation == reputation) &&
            (identical(other.tier, tier) || other.tier == tier));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, displayName, username,
      initials, accentColor, isSystem, reputation, tier);

  /// Create a copy of FeedAuthor
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedAuthorImplCopyWith<_$FeedAuthorImpl> get copyWith =>
      __$$FeedAuthorImplCopyWithImpl<_$FeedAuthorImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedAuthorImplToJson(
      this,
    );
  }
}

abstract class _FeedAuthor implements FeedAuthor {
  const factory _FeedAuthor(
      {required final String id,
      required final String displayName,
      final String? username,
      required final String initials,
      required final String accentColor,
      required final bool isSystem,
      final int? reputation,
      final String? tier}) = _$FeedAuthorImpl;

  factory _FeedAuthor.fromJson(Map<String, dynamic> json) =
      _$FeedAuthorImpl.fromJson;

  @override
  String get id;
  @override
  String get displayName;
  @override
  String? get username;
  @override
  String get initials;
  @override
  String get accentColor;
  @override
  bool get isSystem;
  @override
  int? get reputation;
  @override
  String? get tier;

  /// Create a copy of FeedAuthor
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedAuthorImplCopyWith<_$FeedAuthorImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedCrowdDelta _$FeedCrowdDeltaFromJson(Map<String, dynamic> json) {
  return _FeedCrowdDelta.fromJson(json);
}

/// @nodoc
mixin _$FeedCrowdDelta {
  String get side => throw _privateConstructorUsedError; // home | draw | away
  int get pp => throw _privateConstructorUsedError;
  int get windowMinutes => throw _privateConstructorUsedError;

  /// Serializes this FeedCrowdDelta to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedCrowdDelta
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedCrowdDeltaCopyWith<FeedCrowdDelta> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedCrowdDeltaCopyWith<$Res> {
  factory $FeedCrowdDeltaCopyWith(
          FeedCrowdDelta value, $Res Function(FeedCrowdDelta) then) =
      _$FeedCrowdDeltaCopyWithImpl<$Res, FeedCrowdDelta>;
  @useResult
  $Res call({String side, int pp, int windowMinutes});
}

/// @nodoc
class _$FeedCrowdDeltaCopyWithImpl<$Res, $Val extends FeedCrowdDelta>
    implements $FeedCrowdDeltaCopyWith<$Res> {
  _$FeedCrowdDeltaCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedCrowdDelta
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? side = null,
    Object? pp = null,
    Object? windowMinutes = null,
  }) {
    return _then(_value.copyWith(
      side: null == side
          ? _value.side
          : side // ignore: cast_nullable_to_non_nullable
              as String,
      pp: null == pp
          ? _value.pp
          : pp // ignore: cast_nullable_to_non_nullable
              as int,
      windowMinutes: null == windowMinutes
          ? _value.windowMinutes
          : windowMinutes // ignore: cast_nullable_to_non_nullable
              as int,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedCrowdDeltaImplCopyWith<$Res>
    implements $FeedCrowdDeltaCopyWith<$Res> {
  factory _$$FeedCrowdDeltaImplCopyWith(_$FeedCrowdDeltaImpl value,
          $Res Function(_$FeedCrowdDeltaImpl) then) =
      __$$FeedCrowdDeltaImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String side, int pp, int windowMinutes});
}

/// @nodoc
class __$$FeedCrowdDeltaImplCopyWithImpl<$Res>
    extends _$FeedCrowdDeltaCopyWithImpl<$Res, _$FeedCrowdDeltaImpl>
    implements _$$FeedCrowdDeltaImplCopyWith<$Res> {
  __$$FeedCrowdDeltaImplCopyWithImpl(
      _$FeedCrowdDeltaImpl _value, $Res Function(_$FeedCrowdDeltaImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedCrowdDelta
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? side = null,
    Object? pp = null,
    Object? windowMinutes = null,
  }) {
    return _then(_$FeedCrowdDeltaImpl(
      side: null == side
          ? _value.side
          : side // ignore: cast_nullable_to_non_nullable
              as String,
      pp: null == pp
          ? _value.pp
          : pp // ignore: cast_nullable_to_non_nullable
              as int,
      windowMinutes: null == windowMinutes
          ? _value.windowMinutes
          : windowMinutes // ignore: cast_nullable_to_non_nullable
              as int,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedCrowdDeltaImpl implements _FeedCrowdDelta {
  const _$FeedCrowdDeltaImpl(
      {required this.side, required this.pp, required this.windowMinutes});

  factory _$FeedCrowdDeltaImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedCrowdDeltaImplFromJson(json);

  @override
  final String side;
// home | draw | away
  @override
  final int pp;
  @override
  final int windowMinutes;

  @override
  String toString() {
    return 'FeedCrowdDelta(side: $side, pp: $pp, windowMinutes: $windowMinutes)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedCrowdDeltaImpl &&
            (identical(other.side, side) || other.side == side) &&
            (identical(other.pp, pp) || other.pp == pp) &&
            (identical(other.windowMinutes, windowMinutes) ||
                other.windowMinutes == windowMinutes));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, side, pp, windowMinutes);

  /// Create a copy of FeedCrowdDelta
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedCrowdDeltaImplCopyWith<_$FeedCrowdDeltaImpl> get copyWith =>
      __$$FeedCrowdDeltaImplCopyWithImpl<_$FeedCrowdDeltaImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedCrowdDeltaImplToJson(
      this,
    );
  }
}

abstract class _FeedCrowdDelta implements FeedCrowdDelta {
  const factory _FeedCrowdDelta(
      {required final String side,
      required final int pp,
      required final int windowMinutes}) = _$FeedCrowdDeltaImpl;

  factory _FeedCrowdDelta.fromJson(Map<String, dynamic> json) =
      _$FeedCrowdDeltaImpl.fromJson;

  @override
  String get side; // home | draw | away
  @override
  int get pp;
  @override
  int get windowMinutes;

  /// Create a copy of FeedCrowdDelta
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedCrowdDeltaImplCopyWith<_$FeedCrowdDeltaImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedCrowdSentiment _$FeedCrowdSentimentFromJson(Map<String, dynamic> json) {
  return _FeedCrowdSentiment.fromJson(json);
}

/// @nodoc
mixin _$FeedCrowdSentiment {
  double get homePct => throw _privateConstructorUsedError;
  double get drawPct => throw _privateConstructorUsedError;
  double get awayPct => throw _privateConstructorUsedError;
  int get participants => throw _privateConstructorUsedError;
  FeedCrowdDelta? get delta => throw _privateConstructorUsedError;

  /// Serializes this FeedCrowdSentiment to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedCrowdSentiment
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedCrowdSentimentCopyWith<FeedCrowdSentiment> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedCrowdSentimentCopyWith<$Res> {
  factory $FeedCrowdSentimentCopyWith(
          FeedCrowdSentiment value, $Res Function(FeedCrowdSentiment) then) =
      _$FeedCrowdSentimentCopyWithImpl<$Res, FeedCrowdSentiment>;
  @useResult
  $Res call(
      {double homePct,
      double drawPct,
      double awayPct,
      int participants,
      FeedCrowdDelta? delta});

  $FeedCrowdDeltaCopyWith<$Res>? get delta;
}

/// @nodoc
class _$FeedCrowdSentimentCopyWithImpl<$Res, $Val extends FeedCrowdSentiment>
    implements $FeedCrowdSentimentCopyWith<$Res> {
  _$FeedCrowdSentimentCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedCrowdSentiment
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? homePct = null,
    Object? drawPct = null,
    Object? awayPct = null,
    Object? participants = null,
    Object? delta = freezed,
  }) {
    return _then(_value.copyWith(
      homePct: null == homePct
          ? _value.homePct
          : homePct // ignore: cast_nullable_to_non_nullable
              as double,
      drawPct: null == drawPct
          ? _value.drawPct
          : drawPct // ignore: cast_nullable_to_non_nullable
              as double,
      awayPct: null == awayPct
          ? _value.awayPct
          : awayPct // ignore: cast_nullable_to_non_nullable
              as double,
      participants: null == participants
          ? _value.participants
          : participants // ignore: cast_nullable_to_non_nullable
              as int,
      delta: freezed == delta
          ? _value.delta
          : delta // ignore: cast_nullable_to_non_nullable
              as FeedCrowdDelta?,
    ) as $Val);
  }

  /// Create a copy of FeedCrowdSentiment
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedCrowdDeltaCopyWith<$Res>? get delta {
    if (_value.delta == null) {
      return null;
    }

    return $FeedCrowdDeltaCopyWith<$Res>(_value.delta!, (value) {
      return _then(_value.copyWith(delta: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$FeedCrowdSentimentImplCopyWith<$Res>
    implements $FeedCrowdSentimentCopyWith<$Res> {
  factory _$$FeedCrowdSentimentImplCopyWith(_$FeedCrowdSentimentImpl value,
          $Res Function(_$FeedCrowdSentimentImpl) then) =
      __$$FeedCrowdSentimentImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {double homePct,
      double drawPct,
      double awayPct,
      int participants,
      FeedCrowdDelta? delta});

  @override
  $FeedCrowdDeltaCopyWith<$Res>? get delta;
}

/// @nodoc
class __$$FeedCrowdSentimentImplCopyWithImpl<$Res>
    extends _$FeedCrowdSentimentCopyWithImpl<$Res, _$FeedCrowdSentimentImpl>
    implements _$$FeedCrowdSentimentImplCopyWith<$Res> {
  __$$FeedCrowdSentimentImplCopyWithImpl(_$FeedCrowdSentimentImpl _value,
      $Res Function(_$FeedCrowdSentimentImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedCrowdSentiment
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? homePct = null,
    Object? drawPct = null,
    Object? awayPct = null,
    Object? participants = null,
    Object? delta = freezed,
  }) {
    return _then(_$FeedCrowdSentimentImpl(
      homePct: null == homePct
          ? _value.homePct
          : homePct // ignore: cast_nullable_to_non_nullable
              as double,
      drawPct: null == drawPct
          ? _value.drawPct
          : drawPct // ignore: cast_nullable_to_non_nullable
              as double,
      awayPct: null == awayPct
          ? _value.awayPct
          : awayPct // ignore: cast_nullable_to_non_nullable
              as double,
      participants: null == participants
          ? _value.participants
          : participants // ignore: cast_nullable_to_non_nullable
              as int,
      delta: freezed == delta
          ? _value.delta
          : delta // ignore: cast_nullable_to_non_nullable
              as FeedCrowdDelta?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedCrowdSentimentImpl implements _FeedCrowdSentiment {
  const _$FeedCrowdSentimentImpl(
      {required this.homePct,
      required this.drawPct,
      required this.awayPct,
      required this.participants,
      this.delta});

  factory _$FeedCrowdSentimentImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedCrowdSentimentImplFromJson(json);

  @override
  final double homePct;
  @override
  final double drawPct;
  @override
  final double awayPct;
  @override
  final int participants;
  @override
  final FeedCrowdDelta? delta;

  @override
  String toString() {
    return 'FeedCrowdSentiment(homePct: $homePct, drawPct: $drawPct, awayPct: $awayPct, participants: $participants, delta: $delta)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedCrowdSentimentImpl &&
            (identical(other.homePct, homePct) || other.homePct == homePct) &&
            (identical(other.drawPct, drawPct) || other.drawPct == drawPct) &&
            (identical(other.awayPct, awayPct) || other.awayPct == awayPct) &&
            (identical(other.participants, participants) ||
                other.participants == participants) &&
            (identical(other.delta, delta) || other.delta == delta));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, homePct, drawPct, awayPct, participants, delta);

  /// Create a copy of FeedCrowdSentiment
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedCrowdSentimentImplCopyWith<_$FeedCrowdSentimentImpl> get copyWith =>
      __$$FeedCrowdSentimentImplCopyWithImpl<_$FeedCrowdSentimentImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedCrowdSentimentImplToJson(
      this,
    );
  }
}

abstract class _FeedCrowdSentiment implements FeedCrowdSentiment {
  const factory _FeedCrowdSentiment(
      {required final double homePct,
      required final double drawPct,
      required final double awayPct,
      required final int participants,
      final FeedCrowdDelta? delta}) = _$FeedCrowdSentimentImpl;

  factory _FeedCrowdSentiment.fromJson(Map<String, dynamic> json) =
      _$FeedCrowdSentimentImpl.fromJson;

  @override
  double get homePct;
  @override
  double get drawPct;
  @override
  double get awayPct;
  @override
  int get participants;
  @override
  FeedCrowdDelta? get delta;

  /// Create a copy of FeedCrowdSentiment
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedCrowdSentimentImplCopyWith<_$FeedCrowdSentimentImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedReplyPreviewBody _$FeedReplyPreviewBodyFromJson(Map<String, dynamic> json) {
  return _FeedReplyPreviewBody.fromJson(json);
}

/// @nodoc
mixin _$FeedReplyPreviewBody {
  String get authorDisplayName => throw _privateConstructorUsedError;
  String get text => throw _privateConstructorUsedError;

  /// Serializes this FeedReplyPreviewBody to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedReplyPreviewBody
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedReplyPreviewBodyCopyWith<FeedReplyPreviewBody> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedReplyPreviewBodyCopyWith<$Res> {
  factory $FeedReplyPreviewBodyCopyWith(FeedReplyPreviewBody value,
          $Res Function(FeedReplyPreviewBody) then) =
      _$FeedReplyPreviewBodyCopyWithImpl<$Res, FeedReplyPreviewBody>;
  @useResult
  $Res call({String authorDisplayName, String text});
}

/// @nodoc
class _$FeedReplyPreviewBodyCopyWithImpl<$Res,
        $Val extends FeedReplyPreviewBody>
    implements $FeedReplyPreviewBodyCopyWith<$Res> {
  _$FeedReplyPreviewBodyCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedReplyPreviewBody
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? authorDisplayName = null,
    Object? text = null,
  }) {
    return _then(_value.copyWith(
      authorDisplayName: null == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String,
      text: null == text
          ? _value.text
          : text // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedReplyPreviewBodyImplCopyWith<$Res>
    implements $FeedReplyPreviewBodyCopyWith<$Res> {
  factory _$$FeedReplyPreviewBodyImplCopyWith(_$FeedReplyPreviewBodyImpl value,
          $Res Function(_$FeedReplyPreviewBodyImpl) then) =
      __$$FeedReplyPreviewBodyImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String authorDisplayName, String text});
}

/// @nodoc
class __$$FeedReplyPreviewBodyImplCopyWithImpl<$Res>
    extends _$FeedReplyPreviewBodyCopyWithImpl<$Res, _$FeedReplyPreviewBodyImpl>
    implements _$$FeedReplyPreviewBodyImplCopyWith<$Res> {
  __$$FeedReplyPreviewBodyImplCopyWithImpl(_$FeedReplyPreviewBodyImpl _value,
      $Res Function(_$FeedReplyPreviewBodyImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedReplyPreviewBody
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? authorDisplayName = null,
    Object? text = null,
  }) {
    return _then(_$FeedReplyPreviewBodyImpl(
      authorDisplayName: null == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String,
      text: null == text
          ? _value.text
          : text // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedReplyPreviewBodyImpl implements _FeedReplyPreviewBody {
  const _$FeedReplyPreviewBodyImpl(
      {required this.authorDisplayName, required this.text});

  factory _$FeedReplyPreviewBodyImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedReplyPreviewBodyImplFromJson(json);

  @override
  final String authorDisplayName;
  @override
  final String text;

  @override
  String toString() {
    return 'FeedReplyPreviewBody(authorDisplayName: $authorDisplayName, text: $text)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedReplyPreviewBodyImpl &&
            (identical(other.authorDisplayName, authorDisplayName) ||
                other.authorDisplayName == authorDisplayName) &&
            (identical(other.text, text) || other.text == text));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, authorDisplayName, text);

  /// Create a copy of FeedReplyPreviewBody
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedReplyPreviewBodyImplCopyWith<_$FeedReplyPreviewBodyImpl>
      get copyWith =>
          __$$FeedReplyPreviewBodyImplCopyWithImpl<_$FeedReplyPreviewBodyImpl>(
              this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedReplyPreviewBodyImplToJson(
      this,
    );
  }
}

abstract class _FeedReplyPreviewBody implements FeedReplyPreviewBody {
  const factory _FeedReplyPreviewBody(
      {required final String authorDisplayName,
      required final String text}) = _$FeedReplyPreviewBodyImpl;

  factory _FeedReplyPreviewBody.fromJson(Map<String, dynamic> json) =
      _$FeedReplyPreviewBodyImpl.fromJson;

  @override
  String get authorDisplayName;
  @override
  String get text;

  /// Create a copy of FeedReplyPreviewBody
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedReplyPreviewBodyImplCopyWith<_$FeedReplyPreviewBodyImpl>
      get copyWith => throw _privateConstructorUsedError;
}

FeedReplyPreview _$FeedReplyPreviewFromJson(Map<String, dynamic> json) {
  return _FeedReplyPreview.fromJson(json);
}

/// @nodoc
mixin _$FeedReplyPreview {
  int get count => throw _privateConstructorUsedError;
  FeedReplyPreviewBody? get preview => throw _privateConstructorUsedError;

  /// Serializes this FeedReplyPreview to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedReplyPreview
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedReplyPreviewCopyWith<FeedReplyPreview> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedReplyPreviewCopyWith<$Res> {
  factory $FeedReplyPreviewCopyWith(
          FeedReplyPreview value, $Res Function(FeedReplyPreview) then) =
      _$FeedReplyPreviewCopyWithImpl<$Res, FeedReplyPreview>;
  @useResult
  $Res call({int count, FeedReplyPreviewBody? preview});

  $FeedReplyPreviewBodyCopyWith<$Res>? get preview;
}

/// @nodoc
class _$FeedReplyPreviewCopyWithImpl<$Res, $Val extends FeedReplyPreview>
    implements $FeedReplyPreviewCopyWith<$Res> {
  _$FeedReplyPreviewCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedReplyPreview
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? count = null,
    Object? preview = freezed,
  }) {
    return _then(_value.copyWith(
      count: null == count
          ? _value.count
          : count // ignore: cast_nullable_to_non_nullable
              as int,
      preview: freezed == preview
          ? _value.preview
          : preview // ignore: cast_nullable_to_non_nullable
              as FeedReplyPreviewBody?,
    ) as $Val);
  }

  /// Create a copy of FeedReplyPreview
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedReplyPreviewBodyCopyWith<$Res>? get preview {
    if (_value.preview == null) {
      return null;
    }

    return $FeedReplyPreviewBodyCopyWith<$Res>(_value.preview!, (value) {
      return _then(_value.copyWith(preview: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$FeedReplyPreviewImplCopyWith<$Res>
    implements $FeedReplyPreviewCopyWith<$Res> {
  factory _$$FeedReplyPreviewImplCopyWith(_$FeedReplyPreviewImpl value,
          $Res Function(_$FeedReplyPreviewImpl) then) =
      __$$FeedReplyPreviewImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({int count, FeedReplyPreviewBody? preview});

  @override
  $FeedReplyPreviewBodyCopyWith<$Res>? get preview;
}

/// @nodoc
class __$$FeedReplyPreviewImplCopyWithImpl<$Res>
    extends _$FeedReplyPreviewCopyWithImpl<$Res, _$FeedReplyPreviewImpl>
    implements _$$FeedReplyPreviewImplCopyWith<$Res> {
  __$$FeedReplyPreviewImplCopyWithImpl(_$FeedReplyPreviewImpl _value,
      $Res Function(_$FeedReplyPreviewImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedReplyPreview
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? count = null,
    Object? preview = freezed,
  }) {
    return _then(_$FeedReplyPreviewImpl(
      count: null == count
          ? _value.count
          : count // ignore: cast_nullable_to_non_nullable
              as int,
      preview: freezed == preview
          ? _value.preview
          : preview // ignore: cast_nullable_to_non_nullable
              as FeedReplyPreviewBody?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedReplyPreviewImpl implements _FeedReplyPreview {
  const _$FeedReplyPreviewImpl({required this.count, this.preview});

  factory _$FeedReplyPreviewImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedReplyPreviewImplFromJson(json);

  @override
  final int count;
  @override
  final FeedReplyPreviewBody? preview;

  @override
  String toString() {
    return 'FeedReplyPreview(count: $count, preview: $preview)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedReplyPreviewImpl &&
            (identical(other.count, count) || other.count == count) &&
            (identical(other.preview, preview) || other.preview == preview));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, count, preview);

  /// Create a copy of FeedReplyPreview
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedReplyPreviewImplCopyWith<_$FeedReplyPreviewImpl> get copyWith =>
      __$$FeedReplyPreviewImplCopyWithImpl<_$FeedReplyPreviewImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedReplyPreviewImplToJson(
      this,
    );
  }
}

abstract class _FeedReplyPreview implements FeedReplyPreview {
  const factory _FeedReplyPreview(
      {required final int count,
      final FeedReplyPreviewBody? preview}) = _$FeedReplyPreviewImpl;

  factory _FeedReplyPreview.fromJson(Map<String, dynamic> json) =
      _$FeedReplyPreviewImpl.fromJson;

  @override
  int get count;
  @override
  FeedReplyPreviewBody? get preview;

  /// Create a copy of FeedReplyPreview
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedReplyPreviewImplCopyWith<_$FeedReplyPreviewImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedReactions _$FeedReactionsFromJson(Map<String, dynamic> json) {
  return _FeedReactions.fromJson(json);
}

/// @nodoc
mixin _$FeedReactions {
  int get likes => throw _privateConstructorUsedError;
  int get replies => throw _privateConstructorUsedError;
  int get shares => throw _privateConstructorUsedError;

  /// Serializes this FeedReactions to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedReactions
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedReactionsCopyWith<FeedReactions> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedReactionsCopyWith<$Res> {
  factory $FeedReactionsCopyWith(
          FeedReactions value, $Res Function(FeedReactions) then) =
      _$FeedReactionsCopyWithImpl<$Res, FeedReactions>;
  @useResult
  $Res call({int likes, int replies, int shares});
}

/// @nodoc
class _$FeedReactionsCopyWithImpl<$Res, $Val extends FeedReactions>
    implements $FeedReactionsCopyWith<$Res> {
  _$FeedReactionsCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedReactions
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? likes = null,
    Object? replies = null,
    Object? shares = null,
  }) {
    return _then(_value.copyWith(
      likes: null == likes
          ? _value.likes
          : likes // ignore: cast_nullable_to_non_nullable
              as int,
      replies: null == replies
          ? _value.replies
          : replies // ignore: cast_nullable_to_non_nullable
              as int,
      shares: null == shares
          ? _value.shares
          : shares // ignore: cast_nullable_to_non_nullable
              as int,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedReactionsImplCopyWith<$Res>
    implements $FeedReactionsCopyWith<$Res> {
  factory _$$FeedReactionsImplCopyWith(
          _$FeedReactionsImpl value, $Res Function(_$FeedReactionsImpl) then) =
      __$$FeedReactionsImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({int likes, int replies, int shares});
}

/// @nodoc
class __$$FeedReactionsImplCopyWithImpl<$Res>
    extends _$FeedReactionsCopyWithImpl<$Res, _$FeedReactionsImpl>
    implements _$$FeedReactionsImplCopyWith<$Res> {
  __$$FeedReactionsImplCopyWithImpl(
      _$FeedReactionsImpl _value, $Res Function(_$FeedReactionsImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedReactions
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? likes = null,
    Object? replies = null,
    Object? shares = null,
  }) {
    return _then(_$FeedReactionsImpl(
      likes: null == likes
          ? _value.likes
          : likes // ignore: cast_nullable_to_non_nullable
              as int,
      replies: null == replies
          ? _value.replies
          : replies // ignore: cast_nullable_to_non_nullable
              as int,
      shares: null == shares
          ? _value.shares
          : shares // ignore: cast_nullable_to_non_nullable
              as int,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedReactionsImpl implements _FeedReactions {
  const _$FeedReactionsImpl(
      {this.likes = 0, this.replies = 0, this.shares = 0});

  factory _$FeedReactionsImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedReactionsImplFromJson(json);

  @override
  @JsonKey()
  final int likes;
  @override
  @JsonKey()
  final int replies;
  @override
  @JsonKey()
  final int shares;

  @override
  String toString() {
    return 'FeedReactions(likes: $likes, replies: $replies, shares: $shares)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedReactionsImpl &&
            (identical(other.likes, likes) || other.likes == likes) &&
            (identical(other.replies, replies) || other.replies == replies) &&
            (identical(other.shares, shares) || other.shares == shares));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, likes, replies, shares);

  /// Create a copy of FeedReactions
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedReactionsImplCopyWith<_$FeedReactionsImpl> get copyWith =>
      __$$FeedReactionsImplCopyWithImpl<_$FeedReactionsImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedReactionsImplToJson(
      this,
    );
  }
}

abstract class _FeedReactions implements FeedReactions {
  const factory _FeedReactions(
      {final int likes,
      final int replies,
      final int shares}) = _$FeedReactionsImpl;

  factory _FeedReactions.fromJson(Map<String, dynamic> json) =
      _$FeedReactionsImpl.fromJson;

  @override
  int get likes;
  @override
  int get replies;
  @override
  int get shares;

  /// Create a copy of FeedReactions
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedReactionsImplCopyWith<_$FeedReactionsImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedCommunityRef _$FeedCommunityRefFromJson(Map<String, dynamic> json) {
  return _FeedCommunityRef.fromJson(json);
}

/// @nodoc
mixin _$FeedCommunityRef {
  String get id => throw _privateConstructorUsedError;
  String get handle => throw _privateConstructorUsedError;
  String get name => throw _privateConstructorUsedError;

  /// Serializes this FeedCommunityRef to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedCommunityRef
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedCommunityRefCopyWith<FeedCommunityRef> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedCommunityRefCopyWith<$Res> {
  factory $FeedCommunityRefCopyWith(
          FeedCommunityRef value, $Res Function(FeedCommunityRef) then) =
      _$FeedCommunityRefCopyWithImpl<$Res, FeedCommunityRef>;
  @useResult
  $Res call({String id, String handle, String name});
}

/// @nodoc
class _$FeedCommunityRefCopyWithImpl<$Res, $Val extends FeedCommunityRef>
    implements $FeedCommunityRefCopyWith<$Res> {
  _$FeedCommunityRefCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedCommunityRef
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? handle = null,
    Object? name = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      handle: null == handle
          ? _value.handle
          : handle // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedCommunityRefImplCopyWith<$Res>
    implements $FeedCommunityRefCopyWith<$Res> {
  factory _$$FeedCommunityRefImplCopyWith(_$FeedCommunityRefImpl value,
          $Res Function(_$FeedCommunityRefImpl) then) =
      __$$FeedCommunityRefImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String id, String handle, String name});
}

/// @nodoc
class __$$FeedCommunityRefImplCopyWithImpl<$Res>
    extends _$FeedCommunityRefCopyWithImpl<$Res, _$FeedCommunityRefImpl>
    implements _$$FeedCommunityRefImplCopyWith<$Res> {
  __$$FeedCommunityRefImplCopyWithImpl(_$FeedCommunityRefImpl _value,
      $Res Function(_$FeedCommunityRefImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedCommunityRef
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? handle = null,
    Object? name = null,
  }) {
    return _then(_$FeedCommunityRefImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      handle: null == handle
          ? _value.handle
          : handle // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedCommunityRefImpl implements _FeedCommunityRef {
  const _$FeedCommunityRefImpl(
      {required this.id, required this.handle, required this.name});

  factory _$FeedCommunityRefImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedCommunityRefImplFromJson(json);

  @override
  final String id;
  @override
  final String handle;
  @override
  final String name;

  @override
  String toString() {
    return 'FeedCommunityRef(id: $id, handle: $handle, name: $name)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedCommunityRefImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.handle, handle) || other.handle == handle) &&
            (identical(other.name, name) || other.name == name));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, handle, name);

  /// Create a copy of FeedCommunityRef
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedCommunityRefImplCopyWith<_$FeedCommunityRefImpl> get copyWith =>
      __$$FeedCommunityRefImplCopyWithImpl<_$FeedCommunityRefImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedCommunityRefImplToJson(
      this,
    );
  }
}

abstract class _FeedCommunityRef implements FeedCommunityRef {
  const factory _FeedCommunityRef(
      {required final String id,
      required final String handle,
      required final String name}) = _$FeedCommunityRefImpl;

  factory _FeedCommunityRef.fromJson(Map<String, dynamic> json) =
      _$FeedCommunityRefImpl.fromJson;

  @override
  String get id;
  @override
  String get handle;
  @override
  String get name;

  /// Create a copy of FeedCommunityRef
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedCommunityRefImplCopyWith<_$FeedCommunityRefImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedAgentMeta _$FeedAgentMetaFromJson(Map<String, dynamic> json) {
  return _FeedAgentMeta.fromJson(json);
}

/// @nodoc
mixin _$FeedAgentMeta {
  FeedAgentId get id => throw _privateConstructorUsedError;
  String get label => throw _privateConstructorUsedError;
  double get confidence => throw _privateConstructorUsedError;
  int? get minute =>
      throw _privateConstructorUsedError; // Sprint 2 (Part 6) — trend-post intelligence fields, mirroring
// the Trend Contract the agents publish (title/summary land in
// `title` + the post body; highlights/tags are the structured
// extras). All optional: plain agent commentary renders without.
  String? get title => throw _privateConstructorUsedError;
  List<String> get highlights => throw _privateConstructorUsedError;
  List<String> get tags => throw _privateConstructorUsedError;

  /// Serializes this FeedAgentMeta to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedAgentMeta
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedAgentMetaCopyWith<FeedAgentMeta> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedAgentMetaCopyWith<$Res> {
  factory $FeedAgentMetaCopyWith(
          FeedAgentMeta value, $Res Function(FeedAgentMeta) then) =
      _$FeedAgentMetaCopyWithImpl<$Res, FeedAgentMeta>;
  @useResult
  $Res call(
      {FeedAgentId id,
      String label,
      double confidence,
      int? minute,
      String? title,
      List<String> highlights,
      List<String> tags});
}

/// @nodoc
class _$FeedAgentMetaCopyWithImpl<$Res, $Val extends FeedAgentMeta>
    implements $FeedAgentMetaCopyWith<$Res> {
  _$FeedAgentMetaCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedAgentMeta
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? label = null,
    Object? confidence = null,
    Object? minute = freezed,
    Object? title = freezed,
    Object? highlights = null,
    Object? tags = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as FeedAgentId,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      confidence: null == confidence
          ? _value.confidence
          : confidence // ignore: cast_nullable_to_non_nullable
              as double,
      minute: freezed == minute
          ? _value.minute
          : minute // ignore: cast_nullable_to_non_nullable
              as int?,
      title: freezed == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
              as String?,
      highlights: null == highlights
          ? _value.highlights
          : highlights // ignore: cast_nullable_to_non_nullable
              as List<String>,
      tags: null == tags
          ? _value.tags
          : tags // ignore: cast_nullable_to_non_nullable
              as List<String>,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedAgentMetaImplCopyWith<$Res>
    implements $FeedAgentMetaCopyWith<$Res> {
  factory _$$FeedAgentMetaImplCopyWith(
          _$FeedAgentMetaImpl value, $Res Function(_$FeedAgentMetaImpl) then) =
      __$$FeedAgentMetaImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {FeedAgentId id,
      String label,
      double confidence,
      int? minute,
      String? title,
      List<String> highlights,
      List<String> tags});
}

/// @nodoc
class __$$FeedAgentMetaImplCopyWithImpl<$Res>
    extends _$FeedAgentMetaCopyWithImpl<$Res, _$FeedAgentMetaImpl>
    implements _$$FeedAgentMetaImplCopyWith<$Res> {
  __$$FeedAgentMetaImplCopyWithImpl(
      _$FeedAgentMetaImpl _value, $Res Function(_$FeedAgentMetaImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedAgentMeta
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? label = null,
    Object? confidence = null,
    Object? minute = freezed,
    Object? title = freezed,
    Object? highlights = null,
    Object? tags = null,
  }) {
    return _then(_$FeedAgentMetaImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as FeedAgentId,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      confidence: null == confidence
          ? _value.confidence
          : confidence // ignore: cast_nullable_to_non_nullable
              as double,
      minute: freezed == minute
          ? _value.minute
          : minute // ignore: cast_nullable_to_non_nullable
              as int?,
      title: freezed == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
              as String?,
      highlights: null == highlights
          ? _value._highlights
          : highlights // ignore: cast_nullable_to_non_nullable
              as List<String>,
      tags: null == tags
          ? _value._tags
          : tags // ignore: cast_nullable_to_non_nullable
              as List<String>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedAgentMetaImpl implements _FeedAgentMeta {
  const _$FeedAgentMetaImpl(
      {required this.id,
      required this.label,
      required this.confidence,
      this.minute,
      this.title,
      final List<String> highlights = const <String>[],
      final List<String> tags = const <String>[]})
      : _highlights = highlights,
        _tags = tags;

  factory _$FeedAgentMetaImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedAgentMetaImplFromJson(json);

  @override
  final FeedAgentId id;
  @override
  final String label;
  @override
  final double confidence;
  @override
  final int? minute;
// Sprint 2 (Part 6) — trend-post intelligence fields, mirroring
// the Trend Contract the agents publish (title/summary land in
// `title` + the post body; highlights/tags are the structured
// extras). All optional: plain agent commentary renders without.
  @override
  final String? title;
  final List<String> _highlights;
  @override
  @JsonKey()
  List<String> get highlights {
    if (_highlights is EqualUnmodifiableListView) return _highlights;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_highlights);
  }

  final List<String> _tags;
  @override
  @JsonKey()
  List<String> get tags {
    if (_tags is EqualUnmodifiableListView) return _tags;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_tags);
  }

  @override
  String toString() {
    return 'FeedAgentMeta(id: $id, label: $label, confidence: $confidence, minute: $minute, title: $title, highlights: $highlights, tags: $tags)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedAgentMetaImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.confidence, confidence) ||
                other.confidence == confidence) &&
            (identical(other.minute, minute) || other.minute == minute) &&
            (identical(other.title, title) || other.title == title) &&
            const DeepCollectionEquality()
                .equals(other._highlights, _highlights) &&
            const DeepCollectionEquality().equals(other._tags, _tags));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      id,
      label,
      confidence,
      minute,
      title,
      const DeepCollectionEquality().hash(_highlights),
      const DeepCollectionEquality().hash(_tags));

  /// Create a copy of FeedAgentMeta
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedAgentMetaImplCopyWith<_$FeedAgentMetaImpl> get copyWith =>
      __$$FeedAgentMetaImplCopyWithImpl<_$FeedAgentMetaImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedAgentMetaImplToJson(
      this,
    );
  }
}

abstract class _FeedAgentMeta implements FeedAgentMeta {
  const factory _FeedAgentMeta(
      {required final FeedAgentId id,
      required final String label,
      required final double confidence,
      final int? minute,
      final String? title,
      final List<String> highlights,
      final List<String> tags}) = _$FeedAgentMetaImpl;

  factory _FeedAgentMeta.fromJson(Map<String, dynamic> json) =
      _$FeedAgentMetaImpl.fromJson;

  @override
  FeedAgentId get id;
  @override
  String get label;
  @override
  double get confidence;
  @override
  int?
      get minute; // Sprint 2 (Part 6) — trend-post intelligence fields, mirroring
// the Trend Contract the agents publish (title/summary land in
// `title` + the post body; highlights/tags are the structured
// extras). All optional: plain agent commentary renders without.
  @override
  String? get title;
  @override
  List<String> get highlights;
  @override
  List<String> get tags;

  /// Create a copy of FeedAgentMeta
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedAgentMetaImplCopyWith<_$FeedAgentMetaImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedSponsorMeta _$FeedSponsorMetaFromJson(Map<String, dynamic> json) {
  return _FeedSponsorMeta.fromJson(json);
}

/// @nodoc
mixin _$FeedSponsorMeta {
  String get name => throw _privateConstructorUsedError;
  String get label => throw _privateConstructorUsedError;
  String? get accentColor => throw _privateConstructorUsedError;

  /// Optional click-through URL. Renderer treats it as opaque — the
  /// tap handler decides whether to open in-app or in the system
  /// browser, with appropriate audit logging.
  String? get href => throw _privateConstructorUsedError;

  /// Serializes this FeedSponsorMeta to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedSponsorMeta
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedSponsorMetaCopyWith<FeedSponsorMeta> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedSponsorMetaCopyWith<$Res> {
  factory $FeedSponsorMetaCopyWith(
          FeedSponsorMeta value, $Res Function(FeedSponsorMeta) then) =
      _$FeedSponsorMetaCopyWithImpl<$Res, FeedSponsorMeta>;
  @useResult
  $Res call({String name, String label, String? accentColor, String? href});
}

/// @nodoc
class _$FeedSponsorMetaCopyWithImpl<$Res, $Val extends FeedSponsorMeta>
    implements $FeedSponsorMetaCopyWith<$Res> {
  _$FeedSponsorMetaCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedSponsorMeta
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? name = null,
    Object? label = null,
    Object? accentColor = freezed,
    Object? href = freezed,
  }) {
    return _then(_value.copyWith(
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: freezed == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String?,
      href: freezed == href
          ? _value.href
          : href // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedSponsorMetaImplCopyWith<$Res>
    implements $FeedSponsorMetaCopyWith<$Res> {
  factory _$$FeedSponsorMetaImplCopyWith(_$FeedSponsorMetaImpl value,
          $Res Function(_$FeedSponsorMetaImpl) then) =
      __$$FeedSponsorMetaImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String name, String label, String? accentColor, String? href});
}

/// @nodoc
class __$$FeedSponsorMetaImplCopyWithImpl<$Res>
    extends _$FeedSponsorMetaCopyWithImpl<$Res, _$FeedSponsorMetaImpl>
    implements _$$FeedSponsorMetaImplCopyWith<$Res> {
  __$$FeedSponsorMetaImplCopyWithImpl(
      _$FeedSponsorMetaImpl _value, $Res Function(_$FeedSponsorMetaImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedSponsorMeta
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? name = null,
    Object? label = null,
    Object? accentColor = freezed,
    Object? href = freezed,
  }) {
    return _then(_$FeedSponsorMetaImpl(
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: freezed == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String?,
      href: freezed == href
          ? _value.href
          : href // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedSponsorMetaImpl implements _FeedSponsorMeta {
  const _$FeedSponsorMetaImpl(
      {required this.name,
      this.label = 'Patrocinado',
      this.accentColor,
      this.href});

  factory _$FeedSponsorMetaImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedSponsorMetaImplFromJson(json);

  @override
  final String name;
  @override
  @JsonKey()
  final String label;
  @override
  final String? accentColor;

  /// Optional click-through URL. Renderer treats it as opaque — the
  /// tap handler decides whether to open in-app or in the system
  /// browser, with appropriate audit logging.
  @override
  final String? href;

  @override
  String toString() {
    return 'FeedSponsorMeta(name: $name, label: $label, accentColor: $accentColor, href: $href)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedSponsorMetaImpl &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor) &&
            (identical(other.href, href) || other.href == href));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, name, label, accentColor, href);

  /// Create a copy of FeedSponsorMeta
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedSponsorMetaImplCopyWith<_$FeedSponsorMetaImpl> get copyWith =>
      __$$FeedSponsorMetaImplCopyWithImpl<_$FeedSponsorMetaImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedSponsorMetaImplToJson(
      this,
    );
  }
}

abstract class _FeedSponsorMeta implements FeedSponsorMeta {
  const factory _FeedSponsorMeta(
      {required final String name,
      final String label,
      final String? accentColor,
      final String? href}) = _$FeedSponsorMetaImpl;

  factory _FeedSponsorMeta.fromJson(Map<String, dynamic> json) =
      _$FeedSponsorMetaImpl.fromJson;

  @override
  String get name;
  @override
  String get label;
  @override
  String? get accentColor;

  /// Optional click-through URL. Renderer treats it as opaque — the
  /// tap handler decides whether to open in-app or in the system
  /// browser, with appropriate audit logging.
  @override
  String? get href;

  /// Create a copy of FeedSponsorMeta
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedSponsorMetaImplCopyWith<_$FeedSponsorMetaImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedPost _$FeedPostFromJson(Map<String, dynamic> json) {
  return _FeedPost.fromJson(json);
}

/// @nodoc
mixin _$FeedPost {
  String get id => throw _privateConstructorUsedError;
  FeedPostKind get kind => throw _privateConstructorUsedError;
  FeedAuthor get author => throw _privateConstructorUsedError;
  SignalBadgeData? get badge => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  MatchSummary? get match => throw _privateConstructorUsedError;
  FeedCrowdSentiment? get crowd => throw _privateConstructorUsedError;
  FeedCommunityRef? get community => throw _privateConstructorUsedError;
  FeedAgentMeta? get agent => throw _privateConstructorUsedError;
  FeedSponsorMeta? get sponsor => throw _privateConstructorUsedError;
  FeedReactions get reactions => throw _privateConstructorUsedError;
  bool get likedByMe => throw _privateConstructorUsedError;
  FeedReplyPreview? get replyPreview => throw _privateConstructorUsedError;
  DateTime get ts => throw _privateConstructorUsedError;

  /// Serializes this FeedPost to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedPostCopyWith<FeedPost> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedPostCopyWith<$Res> {
  factory $FeedPostCopyWith(FeedPost value, $Res Function(FeedPost) then) =
      _$FeedPostCopyWithImpl<$Res, FeedPost>;
  @useResult
  $Res call(
      {String id,
      FeedPostKind kind,
      FeedAuthor author,
      SignalBadgeData? badge,
      String body,
      MatchSummary? match,
      FeedCrowdSentiment? crowd,
      FeedCommunityRef? community,
      FeedAgentMeta? agent,
      FeedSponsorMeta? sponsor,
      FeedReactions reactions,
      bool likedByMe,
      FeedReplyPreview? replyPreview,
      DateTime ts});

  $FeedAuthorCopyWith<$Res> get author;
  $SignalBadgeDataCopyWith<$Res>? get badge;
  $MatchSummaryCopyWith<$Res>? get match;
  $FeedCrowdSentimentCopyWith<$Res>? get crowd;
  $FeedCommunityRefCopyWith<$Res>? get community;
  $FeedAgentMetaCopyWith<$Res>? get agent;
  $FeedSponsorMetaCopyWith<$Res>? get sponsor;
  $FeedReactionsCopyWith<$Res> get reactions;
  $FeedReplyPreviewCopyWith<$Res>? get replyPreview;
}

/// @nodoc
class _$FeedPostCopyWithImpl<$Res, $Val extends FeedPost>
    implements $FeedPostCopyWith<$Res> {
  _$FeedPostCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? kind = null,
    Object? author = null,
    Object? badge = freezed,
    Object? body = null,
    Object? match = freezed,
    Object? crowd = freezed,
    Object? community = freezed,
    Object? agent = freezed,
    Object? sponsor = freezed,
    Object? reactions = null,
    Object? likedByMe = null,
    Object? replyPreview = freezed,
    Object? ts = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      kind: null == kind
          ? _value.kind
          : kind // ignore: cast_nullable_to_non_nullable
              as FeedPostKind,
      author: null == author
          ? _value.author
          : author // ignore: cast_nullable_to_non_nullable
              as FeedAuthor,
      badge: freezed == badge
          ? _value.badge
          : badge // ignore: cast_nullable_to_non_nullable
              as SignalBadgeData?,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      match: freezed == match
          ? _value.match
          : match // ignore: cast_nullable_to_non_nullable
              as MatchSummary?,
      crowd: freezed == crowd
          ? _value.crowd
          : crowd // ignore: cast_nullable_to_non_nullable
              as FeedCrowdSentiment?,
      community: freezed == community
          ? _value.community
          : community // ignore: cast_nullable_to_non_nullable
              as FeedCommunityRef?,
      agent: freezed == agent
          ? _value.agent
          : agent // ignore: cast_nullable_to_non_nullable
              as FeedAgentMeta?,
      sponsor: freezed == sponsor
          ? _value.sponsor
          : sponsor // ignore: cast_nullable_to_non_nullable
              as FeedSponsorMeta?,
      reactions: null == reactions
          ? _value.reactions
          : reactions // ignore: cast_nullable_to_non_nullable
              as FeedReactions,
      likedByMe: null == likedByMe
          ? _value.likedByMe
          : likedByMe // ignore: cast_nullable_to_non_nullable
              as bool,
      replyPreview: freezed == replyPreview
          ? _value.replyPreview
          : replyPreview // ignore: cast_nullable_to_non_nullable
              as FeedReplyPreview?,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedAuthorCopyWith<$Res> get author {
    return $FeedAuthorCopyWith<$Res>(_value.author, (value) {
      return _then(_value.copyWith(author: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $SignalBadgeDataCopyWith<$Res>? get badge {
    if (_value.badge == null) {
      return null;
    }

    return $SignalBadgeDataCopyWith<$Res>(_value.badge!, (value) {
      return _then(_value.copyWith(badge: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchSummaryCopyWith<$Res>? get match {
    if (_value.match == null) {
      return null;
    }

    return $MatchSummaryCopyWith<$Res>(_value.match!, (value) {
      return _then(_value.copyWith(match: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedCrowdSentimentCopyWith<$Res>? get crowd {
    if (_value.crowd == null) {
      return null;
    }

    return $FeedCrowdSentimentCopyWith<$Res>(_value.crowd!, (value) {
      return _then(_value.copyWith(crowd: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedCommunityRefCopyWith<$Res>? get community {
    if (_value.community == null) {
      return null;
    }

    return $FeedCommunityRefCopyWith<$Res>(_value.community!, (value) {
      return _then(_value.copyWith(community: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedAgentMetaCopyWith<$Res>? get agent {
    if (_value.agent == null) {
      return null;
    }

    return $FeedAgentMetaCopyWith<$Res>(_value.agent!, (value) {
      return _then(_value.copyWith(agent: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedSponsorMetaCopyWith<$Res>? get sponsor {
    if (_value.sponsor == null) {
      return null;
    }

    return $FeedSponsorMetaCopyWith<$Res>(_value.sponsor!, (value) {
      return _then(_value.copyWith(sponsor: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedReactionsCopyWith<$Res> get reactions {
    return $FeedReactionsCopyWith<$Res>(_value.reactions, (value) {
      return _then(_value.copyWith(reactions: value) as $Val);
    });
  }

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $FeedReplyPreviewCopyWith<$Res>? get replyPreview {
    if (_value.replyPreview == null) {
      return null;
    }

    return $FeedReplyPreviewCopyWith<$Res>(_value.replyPreview!, (value) {
      return _then(_value.copyWith(replyPreview: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$FeedPostImplCopyWith<$Res>
    implements $FeedPostCopyWith<$Res> {
  factory _$$FeedPostImplCopyWith(
          _$FeedPostImpl value, $Res Function(_$FeedPostImpl) then) =
      __$$FeedPostImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      FeedPostKind kind,
      FeedAuthor author,
      SignalBadgeData? badge,
      String body,
      MatchSummary? match,
      FeedCrowdSentiment? crowd,
      FeedCommunityRef? community,
      FeedAgentMeta? agent,
      FeedSponsorMeta? sponsor,
      FeedReactions reactions,
      bool likedByMe,
      FeedReplyPreview? replyPreview,
      DateTime ts});

  @override
  $FeedAuthorCopyWith<$Res> get author;
  @override
  $SignalBadgeDataCopyWith<$Res>? get badge;
  @override
  $MatchSummaryCopyWith<$Res>? get match;
  @override
  $FeedCrowdSentimentCopyWith<$Res>? get crowd;
  @override
  $FeedCommunityRefCopyWith<$Res>? get community;
  @override
  $FeedAgentMetaCopyWith<$Res>? get agent;
  @override
  $FeedSponsorMetaCopyWith<$Res>? get sponsor;
  @override
  $FeedReactionsCopyWith<$Res> get reactions;
  @override
  $FeedReplyPreviewCopyWith<$Res>? get replyPreview;
}

/// @nodoc
class __$$FeedPostImplCopyWithImpl<$Res>
    extends _$FeedPostCopyWithImpl<$Res, _$FeedPostImpl>
    implements _$$FeedPostImplCopyWith<$Res> {
  __$$FeedPostImplCopyWithImpl(
      _$FeedPostImpl _value, $Res Function(_$FeedPostImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? kind = null,
    Object? author = null,
    Object? badge = freezed,
    Object? body = null,
    Object? match = freezed,
    Object? crowd = freezed,
    Object? community = freezed,
    Object? agent = freezed,
    Object? sponsor = freezed,
    Object? reactions = null,
    Object? likedByMe = null,
    Object? replyPreview = freezed,
    Object? ts = null,
  }) {
    return _then(_$FeedPostImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      kind: null == kind
          ? _value.kind
          : kind // ignore: cast_nullable_to_non_nullable
              as FeedPostKind,
      author: null == author
          ? _value.author
          : author // ignore: cast_nullable_to_non_nullable
              as FeedAuthor,
      badge: freezed == badge
          ? _value.badge
          : badge // ignore: cast_nullable_to_non_nullable
              as SignalBadgeData?,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      match: freezed == match
          ? _value.match
          : match // ignore: cast_nullable_to_non_nullable
              as MatchSummary?,
      crowd: freezed == crowd
          ? _value.crowd
          : crowd // ignore: cast_nullable_to_non_nullable
              as FeedCrowdSentiment?,
      community: freezed == community
          ? _value.community
          : community // ignore: cast_nullable_to_non_nullable
              as FeedCommunityRef?,
      agent: freezed == agent
          ? _value.agent
          : agent // ignore: cast_nullable_to_non_nullable
              as FeedAgentMeta?,
      sponsor: freezed == sponsor
          ? _value.sponsor
          : sponsor // ignore: cast_nullable_to_non_nullable
              as FeedSponsorMeta?,
      reactions: null == reactions
          ? _value.reactions
          : reactions // ignore: cast_nullable_to_non_nullable
              as FeedReactions,
      likedByMe: null == likedByMe
          ? _value.likedByMe
          : likedByMe // ignore: cast_nullable_to_non_nullable
              as bool,
      replyPreview: freezed == replyPreview
          ? _value.replyPreview
          : replyPreview // ignore: cast_nullable_to_non_nullable
              as FeedReplyPreview?,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedPostImpl implements _FeedPost {
  const _$FeedPostImpl(
      {required this.id,
      required this.kind,
      required this.author,
      this.badge,
      required this.body,
      this.match,
      this.crowd,
      this.community,
      this.agent,
      this.sponsor,
      this.reactions = const FeedReactions(),
      this.likedByMe = false,
      this.replyPreview,
      required this.ts});

  factory _$FeedPostImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedPostImplFromJson(json);

  @override
  final String id;
  @override
  final FeedPostKind kind;
  @override
  final FeedAuthor author;
  @override
  final SignalBadgeData? badge;
  @override
  final String body;
  @override
  final MatchSummary? match;
  @override
  final FeedCrowdSentiment? crowd;
  @override
  final FeedCommunityRef? community;
  @override
  final FeedAgentMeta? agent;
  @override
  final FeedSponsorMeta? sponsor;
  @override
  @JsonKey()
  final FeedReactions reactions;
  @override
  @JsonKey()
  final bool likedByMe;
  @override
  final FeedReplyPreview? replyPreview;
  @override
  final DateTime ts;

  @override
  String toString() {
    return 'FeedPost(id: $id, kind: $kind, author: $author, badge: $badge, body: $body, match: $match, crowd: $crowd, community: $community, agent: $agent, sponsor: $sponsor, reactions: $reactions, likedByMe: $likedByMe, replyPreview: $replyPreview, ts: $ts)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedPostImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.kind, kind) || other.kind == kind) &&
            (identical(other.author, author) || other.author == author) &&
            (identical(other.badge, badge) || other.badge == badge) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.match, match) || other.match == match) &&
            (identical(other.crowd, crowd) || other.crowd == crowd) &&
            (identical(other.community, community) ||
                other.community == community) &&
            (identical(other.agent, agent) || other.agent == agent) &&
            (identical(other.sponsor, sponsor) || other.sponsor == sponsor) &&
            (identical(other.reactions, reactions) ||
                other.reactions == reactions) &&
            (identical(other.likedByMe, likedByMe) ||
                other.likedByMe == likedByMe) &&
            (identical(other.replyPreview, replyPreview) ||
                other.replyPreview == replyPreview) &&
            (identical(other.ts, ts) || other.ts == ts));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      id,
      kind,
      author,
      badge,
      body,
      match,
      crowd,
      community,
      agent,
      sponsor,
      reactions,
      likedByMe,
      replyPreview,
      ts);

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedPostImplCopyWith<_$FeedPostImpl> get copyWith =>
      __$$FeedPostImplCopyWithImpl<_$FeedPostImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedPostImplToJson(
      this,
    );
  }
}

abstract class _FeedPost implements FeedPost {
  const factory _FeedPost(
      {required final String id,
      required final FeedPostKind kind,
      required final FeedAuthor author,
      final SignalBadgeData? badge,
      required final String body,
      final MatchSummary? match,
      final FeedCrowdSentiment? crowd,
      final FeedCommunityRef? community,
      final FeedAgentMeta? agent,
      final FeedSponsorMeta? sponsor,
      final FeedReactions reactions,
      final bool likedByMe,
      final FeedReplyPreview? replyPreview,
      required final DateTime ts}) = _$FeedPostImpl;

  factory _FeedPost.fromJson(Map<String, dynamic> json) =
      _$FeedPostImpl.fromJson;

  @override
  String get id;
  @override
  FeedPostKind get kind;
  @override
  FeedAuthor get author;
  @override
  SignalBadgeData? get badge;
  @override
  String get body;
  @override
  MatchSummary? get match;
  @override
  FeedCrowdSentiment? get crowd;
  @override
  FeedCommunityRef? get community;
  @override
  FeedAgentMeta? get agent;
  @override
  FeedSponsorMeta? get sponsor;
  @override
  FeedReactions get reactions;
  @override
  bool get likedByMe;
  @override
  FeedReplyPreview? get replyPreview;
  @override
  DateTime get ts;

  /// Create a copy of FeedPost
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedPostImplCopyWith<_$FeedPostImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

FeedPage _$FeedPageFromJson(Map<String, dynamic> json) {
  return _FeedPage.fromJson(json);
}

/// @nodoc
mixin _$FeedPage {
  List<FeedPost> get items => throw _privateConstructorUsedError;
  String? get nextCursor => throw _privateConstructorUsedError;

  /// Serializes this FeedPage to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of FeedPage
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $FeedPageCopyWith<FeedPage> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $FeedPageCopyWith<$Res> {
  factory $FeedPageCopyWith(FeedPage value, $Res Function(FeedPage) then) =
      _$FeedPageCopyWithImpl<$Res, FeedPage>;
  @useResult
  $Res call({List<FeedPost> items, String? nextCursor});
}

/// @nodoc
class _$FeedPageCopyWithImpl<$Res, $Val extends FeedPage>
    implements $FeedPageCopyWith<$Res> {
  _$FeedPageCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of FeedPage
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? items = null,
    Object? nextCursor = freezed,
  }) {
    return _then(_value.copyWith(
      items: null == items
          ? _value.items
          : items // ignore: cast_nullable_to_non_nullable
              as List<FeedPost>,
      nextCursor: freezed == nextCursor
          ? _value.nextCursor
          : nextCursor // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$FeedPageImplCopyWith<$Res>
    implements $FeedPageCopyWith<$Res> {
  factory _$$FeedPageImplCopyWith(
          _$FeedPageImpl value, $Res Function(_$FeedPageImpl) then) =
      __$$FeedPageImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({List<FeedPost> items, String? nextCursor});
}

/// @nodoc
class __$$FeedPageImplCopyWithImpl<$Res>
    extends _$FeedPageCopyWithImpl<$Res, _$FeedPageImpl>
    implements _$$FeedPageImplCopyWith<$Res> {
  __$$FeedPageImplCopyWithImpl(
      _$FeedPageImpl _value, $Res Function(_$FeedPageImpl) _then)
      : super(_value, _then);

  /// Create a copy of FeedPage
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? items = null,
    Object? nextCursor = freezed,
  }) {
    return _then(_$FeedPageImpl(
      items: null == items
          ? _value._items
          : items // ignore: cast_nullable_to_non_nullable
              as List<FeedPost>,
      nextCursor: freezed == nextCursor
          ? _value.nextCursor
          : nextCursor // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$FeedPageImpl implements _FeedPage {
  const _$FeedPageImpl({required final List<FeedPost> items, this.nextCursor})
      : _items = items;

  factory _$FeedPageImpl.fromJson(Map<String, dynamic> json) =>
      _$$FeedPageImplFromJson(json);

  final List<FeedPost> _items;
  @override
  List<FeedPost> get items {
    if (_items is EqualUnmodifiableListView) return _items;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_items);
  }

  @override
  final String? nextCursor;

  @override
  String toString() {
    return 'FeedPage(items: $items, nextCursor: $nextCursor)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$FeedPageImpl &&
            const DeepCollectionEquality().equals(other._items, _items) &&
            (identical(other.nextCursor, nextCursor) ||
                other.nextCursor == nextCursor));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType, const DeepCollectionEquality().hash(_items), nextCursor);

  /// Create a copy of FeedPage
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$FeedPageImplCopyWith<_$FeedPageImpl> get copyWith =>
      __$$FeedPageImplCopyWithImpl<_$FeedPageImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$FeedPageImplToJson(
      this,
    );
  }
}

abstract class _FeedPage implements FeedPage {
  const factory _FeedPage(
      {required final List<FeedPost> items,
      final String? nextCursor}) = _$FeedPageImpl;

  factory _FeedPage.fromJson(Map<String, dynamic> json) =
      _$FeedPageImpl.fromJson;

  @override
  List<FeedPost> get items;
  @override
  String? get nextCursor;

  /// Create a copy of FeedPage
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$FeedPageImplCopyWith<_$FeedPageImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
