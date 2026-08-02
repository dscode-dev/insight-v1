// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'radar.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

TrendingMatch _$TrendingMatchFromJson(Map<String, dynamic> json) {
  return _TrendingMatch.fromJson(json);
}

/// @nodoc
mixin _$TrendingMatch {
  MatchSummary get summary => throw _privateConstructorUsedError;
  String get reason => throw _privateConstructorUsedError;

  /// Serializes this TrendingMatch to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TrendingMatch
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TrendingMatchCopyWith<TrendingMatch> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TrendingMatchCopyWith<$Res> {
  factory $TrendingMatchCopyWith(
          TrendingMatch value, $Res Function(TrendingMatch) then) =
      _$TrendingMatchCopyWithImpl<$Res, TrendingMatch>;
  @useResult
  $Res call({MatchSummary summary, String reason});

  $MatchSummaryCopyWith<$Res> get summary;
}

/// @nodoc
class _$TrendingMatchCopyWithImpl<$Res, $Val extends TrendingMatch>
    implements $TrendingMatchCopyWith<$Res> {
  _$TrendingMatchCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TrendingMatch
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? summary = null,
    Object? reason = null,
  }) {
    return _then(_value.copyWith(
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as MatchSummary,
      reason: null == reason
          ? _value.reason
          : reason // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }

  /// Create a copy of TrendingMatch
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchSummaryCopyWith<$Res> get summary {
    return $MatchSummaryCopyWith<$Res>(_value.summary, (value) {
      return _then(_value.copyWith(summary: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$TrendingMatchImplCopyWith<$Res>
    implements $TrendingMatchCopyWith<$Res> {
  factory _$$TrendingMatchImplCopyWith(
          _$TrendingMatchImpl value, $Res Function(_$TrendingMatchImpl) then) =
      __$$TrendingMatchImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({MatchSummary summary, String reason});

  @override
  $MatchSummaryCopyWith<$Res> get summary;
}

/// @nodoc
class __$$TrendingMatchImplCopyWithImpl<$Res>
    extends _$TrendingMatchCopyWithImpl<$Res, _$TrendingMatchImpl>
    implements _$$TrendingMatchImplCopyWith<$Res> {
  __$$TrendingMatchImplCopyWithImpl(
      _$TrendingMatchImpl _value, $Res Function(_$TrendingMatchImpl) _then)
      : super(_value, _then);

  /// Create a copy of TrendingMatch
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? summary = null,
    Object? reason = null,
  }) {
    return _then(_$TrendingMatchImpl(
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as MatchSummary,
      reason: null == reason
          ? _value.reason
          : reason // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$TrendingMatchImpl implements _TrendingMatch {
  const _$TrendingMatchImpl({required this.summary, required this.reason});

  factory _$TrendingMatchImpl.fromJson(Map<String, dynamic> json) =>
      _$$TrendingMatchImplFromJson(json);

  @override
  final MatchSummary summary;
  @override
  final String reason;

  @override
  String toString() {
    return 'TrendingMatch(summary: $summary, reason: $reason)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TrendingMatchImpl &&
            (identical(other.summary, summary) || other.summary == summary) &&
            (identical(other.reason, reason) || other.reason == reason));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, summary, reason);

  /// Create a copy of TrendingMatch
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TrendingMatchImplCopyWith<_$TrendingMatchImpl> get copyWith =>
      __$$TrendingMatchImplCopyWithImpl<_$TrendingMatchImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$TrendingMatchImplToJson(
      this,
    );
  }
}

abstract class _TrendingMatch implements TrendingMatch {
  const factory _TrendingMatch(
      {required final MatchSummary summary,
      required final String reason}) = _$TrendingMatchImpl;

  factory _TrendingMatch.fromJson(Map<String, dynamic> json) =
      _$TrendingMatchImpl.fromJson;

  @override
  MatchSummary get summary;
  @override
  String get reason;

  /// Create a copy of TrendingMatch
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TrendingMatchImplCopyWith<_$TrendingMatchImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MarketMovement _$MarketMovementFromJson(Map<String, dynamic> json) {
  return _MarketMovement.fromJson(json);
}

/// @nodoc
mixin _$MarketMovement {
  String get id => throw _privateConstructorUsedError;
  String get matchId => throw _privateConstructorUsedError;
  String get matchLabel => throw _privateConstructorUsedError; // "PAL × FLA"
  String get league => throw _privateConstructorUsedError;
  MovementDirection get direction => throw _privateConstructorUsedError;
  String get summary =>
      throw _privateConstructorUsedError; // "Empate 3.20 → 3.05 em 8 casas"
  double get magnitude => throw _privateConstructorUsedError; // 0..1
  DateTime get ts => throw _privateConstructorUsedError;

  /// Serializes this MarketMovement to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MarketMovement
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MarketMovementCopyWith<MarketMovement> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MarketMovementCopyWith<$Res> {
  factory $MarketMovementCopyWith(
          MarketMovement value, $Res Function(MarketMovement) then) =
      _$MarketMovementCopyWithImpl<$Res, MarketMovement>;
  @useResult
  $Res call(
      {String id,
      String matchId,
      String matchLabel,
      String league,
      MovementDirection direction,
      String summary,
      double magnitude,
      DateTime ts});
}

/// @nodoc
class _$MarketMovementCopyWithImpl<$Res, $Val extends MarketMovement>
    implements $MarketMovementCopyWith<$Res> {
  _$MarketMovementCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MarketMovement
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? matchId = null,
    Object? matchLabel = null,
    Object? league = null,
    Object? direction = null,
    Object? summary = null,
    Object? magnitude = null,
    Object? ts = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      matchLabel: null == matchLabel
          ? _value.matchLabel
          : matchLabel // ignore: cast_nullable_to_non_nullable
              as String,
      league: null == league
          ? _value.league
          : league // ignore: cast_nullable_to_non_nullable
              as String,
      direction: null == direction
          ? _value.direction
          : direction // ignore: cast_nullable_to_non_nullable
              as MovementDirection,
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as String,
      magnitude: null == magnitude
          ? _value.magnitude
          : magnitude // ignore: cast_nullable_to_non_nullable
              as double,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$MarketMovementImplCopyWith<$Res>
    implements $MarketMovementCopyWith<$Res> {
  factory _$$MarketMovementImplCopyWith(_$MarketMovementImpl value,
          $Res Function(_$MarketMovementImpl) then) =
      __$$MarketMovementImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String matchId,
      String matchLabel,
      String league,
      MovementDirection direction,
      String summary,
      double magnitude,
      DateTime ts});
}

/// @nodoc
class __$$MarketMovementImplCopyWithImpl<$Res>
    extends _$MarketMovementCopyWithImpl<$Res, _$MarketMovementImpl>
    implements _$$MarketMovementImplCopyWith<$Res> {
  __$$MarketMovementImplCopyWithImpl(
      _$MarketMovementImpl _value, $Res Function(_$MarketMovementImpl) _then)
      : super(_value, _then);

  /// Create a copy of MarketMovement
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? matchId = null,
    Object? matchLabel = null,
    Object? league = null,
    Object? direction = null,
    Object? summary = null,
    Object? magnitude = null,
    Object? ts = null,
  }) {
    return _then(_$MarketMovementImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      matchLabel: null == matchLabel
          ? _value.matchLabel
          : matchLabel // ignore: cast_nullable_to_non_nullable
              as String,
      league: null == league
          ? _value.league
          : league // ignore: cast_nullable_to_non_nullable
              as String,
      direction: null == direction
          ? _value.direction
          : direction // ignore: cast_nullable_to_non_nullable
              as MovementDirection,
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as String,
      magnitude: null == magnitude
          ? _value.magnitude
          : magnitude // ignore: cast_nullable_to_non_nullable
              as double,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MarketMovementImpl implements _MarketMovement {
  const _$MarketMovementImpl(
      {required this.id,
      required this.matchId,
      required this.matchLabel,
      required this.league,
      required this.direction,
      required this.summary,
      required this.magnitude,
      required this.ts});

  factory _$MarketMovementImpl.fromJson(Map<String, dynamic> json) =>
      _$$MarketMovementImplFromJson(json);

  @override
  final String id;
  @override
  final String matchId;
  @override
  final String matchLabel;
// "PAL × FLA"
  @override
  final String league;
  @override
  final MovementDirection direction;
  @override
  final String summary;
// "Empate 3.20 → 3.05 em 8 casas"
  @override
  final double magnitude;
// 0..1
  @override
  final DateTime ts;

  @override
  String toString() {
    return 'MarketMovement(id: $id, matchId: $matchId, matchLabel: $matchLabel, league: $league, direction: $direction, summary: $summary, magnitude: $magnitude, ts: $ts)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MarketMovementImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.matchId, matchId) || other.matchId == matchId) &&
            (identical(other.matchLabel, matchLabel) ||
                other.matchLabel == matchLabel) &&
            (identical(other.league, league) || other.league == league) &&
            (identical(other.direction, direction) ||
                other.direction == direction) &&
            (identical(other.summary, summary) || other.summary == summary) &&
            (identical(other.magnitude, magnitude) ||
                other.magnitude == magnitude) &&
            (identical(other.ts, ts) || other.ts == ts));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, matchId, matchLabel, league,
      direction, summary, magnitude, ts);

  /// Create a copy of MarketMovement
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MarketMovementImplCopyWith<_$MarketMovementImpl> get copyWith =>
      __$$MarketMovementImplCopyWithImpl<_$MarketMovementImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MarketMovementImplToJson(
      this,
    );
  }
}

abstract class _MarketMovement implements MarketMovement {
  const factory _MarketMovement(
      {required final String id,
      required final String matchId,
      required final String matchLabel,
      required final String league,
      required final MovementDirection direction,
      required final String summary,
      required final double magnitude,
      required final DateTime ts}) = _$MarketMovementImpl;

  factory _MarketMovement.fromJson(Map<String, dynamic> json) =
      _$MarketMovementImpl.fromJson;

  @override
  String get id;
  @override
  String get matchId;
  @override
  String get matchLabel; // "PAL × FLA"
  @override
  String get league;
  @override
  MovementDirection get direction;
  @override
  String get summary; // "Empate 3.20 → 3.05 em 8 casas"
  @override
  double get magnitude; // 0..1
  @override
  DateTime get ts;

  /// Create a copy of MarketMovement
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MarketMovementImplCopyWith<_$MarketMovementImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

CommunitySignalCard _$CommunitySignalCardFromJson(Map<String, dynamic> json) {
  return _CommunitySignalCard.fromJson(json);
}

/// @nodoc
mixin _$CommunitySignalCard {
  String get id => throw _privateConstructorUsedError;
  String get authorDisplayName => throw _privateConstructorUsedError;
  String get authorAccent => throw _privateConstructorUsedError;
  String get authorInitials => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  String get matchLabel => throw _privateConstructorUsedError;
  double get confidence => throw _privateConstructorUsedError;
  DateTime get ts => throw _privateConstructorUsedError;

  /// Serializes this CommunitySignalCard to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of CommunitySignalCard
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CommunitySignalCardCopyWith<CommunitySignalCard> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CommunitySignalCardCopyWith<$Res> {
  factory $CommunitySignalCardCopyWith(
          CommunitySignalCard value, $Res Function(CommunitySignalCard) then) =
      _$CommunitySignalCardCopyWithImpl<$Res, CommunitySignalCard>;
  @useResult
  $Res call(
      {String id,
      String authorDisplayName,
      String authorAccent,
      String authorInitials,
      String body,
      String matchLabel,
      double confidence,
      DateTime ts});
}

/// @nodoc
class _$CommunitySignalCardCopyWithImpl<$Res, $Val extends CommunitySignalCard>
    implements $CommunitySignalCardCopyWith<$Res> {
  _$CommunitySignalCardCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of CommunitySignalCard
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? authorDisplayName = null,
    Object? authorAccent = null,
    Object? authorInitials = null,
    Object? body = null,
    Object? matchLabel = null,
    Object? confidence = null,
    Object? ts = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      authorDisplayName: null == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String,
      authorAccent: null == authorAccent
          ? _value.authorAccent
          : authorAccent // ignore: cast_nullable_to_non_nullable
              as String,
      authorInitials: null == authorInitials
          ? _value.authorInitials
          : authorInitials // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      matchLabel: null == matchLabel
          ? _value.matchLabel
          : matchLabel // ignore: cast_nullable_to_non_nullable
              as String,
      confidence: null == confidence
          ? _value.confidence
          : confidence // ignore: cast_nullable_to_non_nullable
              as double,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CommunitySignalCardImplCopyWith<$Res>
    implements $CommunitySignalCardCopyWith<$Res> {
  factory _$$CommunitySignalCardImplCopyWith(_$CommunitySignalCardImpl value,
          $Res Function(_$CommunitySignalCardImpl) then) =
      __$$CommunitySignalCardImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String authorDisplayName,
      String authorAccent,
      String authorInitials,
      String body,
      String matchLabel,
      double confidence,
      DateTime ts});
}

/// @nodoc
class __$$CommunitySignalCardImplCopyWithImpl<$Res>
    extends _$CommunitySignalCardCopyWithImpl<$Res, _$CommunitySignalCardImpl>
    implements _$$CommunitySignalCardImplCopyWith<$Res> {
  __$$CommunitySignalCardImplCopyWithImpl(_$CommunitySignalCardImpl _value,
      $Res Function(_$CommunitySignalCardImpl) _then)
      : super(_value, _then);

  /// Create a copy of CommunitySignalCard
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? authorDisplayName = null,
    Object? authorAccent = null,
    Object? authorInitials = null,
    Object? body = null,
    Object? matchLabel = null,
    Object? confidence = null,
    Object? ts = null,
  }) {
    return _then(_$CommunitySignalCardImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      authorDisplayName: null == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String,
      authorAccent: null == authorAccent
          ? _value.authorAccent
          : authorAccent // ignore: cast_nullable_to_non_nullable
              as String,
      authorInitials: null == authorInitials
          ? _value.authorInitials
          : authorInitials // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      matchLabel: null == matchLabel
          ? _value.matchLabel
          : matchLabel // ignore: cast_nullable_to_non_nullable
              as String,
      confidence: null == confidence
          ? _value.confidence
          : confidence // ignore: cast_nullable_to_non_nullable
              as double,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$CommunitySignalCardImpl implements _CommunitySignalCard {
  const _$CommunitySignalCardImpl(
      {required this.id,
      required this.authorDisplayName,
      required this.authorAccent,
      required this.authorInitials,
      required this.body,
      required this.matchLabel,
      required this.confidence,
      required this.ts});

  factory _$CommunitySignalCardImpl.fromJson(Map<String, dynamic> json) =>
      _$$CommunitySignalCardImplFromJson(json);

  @override
  final String id;
  @override
  final String authorDisplayName;
  @override
  final String authorAccent;
  @override
  final String authorInitials;
  @override
  final String body;
  @override
  final String matchLabel;
  @override
  final double confidence;
  @override
  final DateTime ts;

  @override
  String toString() {
    return 'CommunitySignalCard(id: $id, authorDisplayName: $authorDisplayName, authorAccent: $authorAccent, authorInitials: $authorInitials, body: $body, matchLabel: $matchLabel, confidence: $confidence, ts: $ts)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CommunitySignalCardImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.authorDisplayName, authorDisplayName) ||
                other.authorDisplayName == authorDisplayName) &&
            (identical(other.authorAccent, authorAccent) ||
                other.authorAccent == authorAccent) &&
            (identical(other.authorInitials, authorInitials) ||
                other.authorInitials == authorInitials) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.matchLabel, matchLabel) ||
                other.matchLabel == matchLabel) &&
            (identical(other.confidence, confidence) ||
                other.confidence == confidence) &&
            (identical(other.ts, ts) || other.ts == ts));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, authorDisplayName,
      authorAccent, authorInitials, body, matchLabel, confidence, ts);

  /// Create a copy of CommunitySignalCard
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CommunitySignalCardImplCopyWith<_$CommunitySignalCardImpl> get copyWith =>
      __$$CommunitySignalCardImplCopyWithImpl<_$CommunitySignalCardImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CommunitySignalCardImplToJson(
      this,
    );
  }
}

abstract class _CommunitySignalCard implements CommunitySignalCard {
  const factory _CommunitySignalCard(
      {required final String id,
      required final String authorDisplayName,
      required final String authorAccent,
      required final String authorInitials,
      required final String body,
      required final String matchLabel,
      required final double confidence,
      required final DateTime ts}) = _$CommunitySignalCardImpl;

  factory _CommunitySignalCard.fromJson(Map<String, dynamic> json) =
      _$CommunitySignalCardImpl.fromJson;

  @override
  String get id;
  @override
  String get authorDisplayName;
  @override
  String get authorAccent;
  @override
  String get authorInitials;
  @override
  String get body;
  @override
  String get matchLabel;
  @override
  double get confidence;
  @override
  DateTime get ts;

  /// Create a copy of CommunitySignalCard
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CommunitySignalCardImplCopyWith<_$CommunitySignalCardImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

RadarBundle _$RadarBundleFromJson(Map<String, dynamic> json) {
  return _RadarBundle.fromJson(json);
}

/// @nodoc
mixin _$RadarBundle {
  List<TrendingMatch> get trending => throw _privateConstructorUsedError;
  List<MarketMovement> get movements => throw _privateConstructorUsedError;
  List<CommunitySignalCard> get signals => throw _privateConstructorUsedError;

  /// Serializes this RadarBundle to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of RadarBundle
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $RadarBundleCopyWith<RadarBundle> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $RadarBundleCopyWith<$Res> {
  factory $RadarBundleCopyWith(
          RadarBundle value, $Res Function(RadarBundle) then) =
      _$RadarBundleCopyWithImpl<$Res, RadarBundle>;
  @useResult
  $Res call(
      {List<TrendingMatch> trending,
      List<MarketMovement> movements,
      List<CommunitySignalCard> signals});
}

/// @nodoc
class _$RadarBundleCopyWithImpl<$Res, $Val extends RadarBundle>
    implements $RadarBundleCopyWith<$Res> {
  _$RadarBundleCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of RadarBundle
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? trending = null,
    Object? movements = null,
    Object? signals = null,
  }) {
    return _then(_value.copyWith(
      trending: null == trending
          ? _value.trending
          : trending // ignore: cast_nullable_to_non_nullable
              as List<TrendingMatch>,
      movements: null == movements
          ? _value.movements
          : movements // ignore: cast_nullable_to_non_nullable
              as List<MarketMovement>,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as List<CommunitySignalCard>,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$RadarBundleImplCopyWith<$Res>
    implements $RadarBundleCopyWith<$Res> {
  factory _$$RadarBundleImplCopyWith(
          _$RadarBundleImpl value, $Res Function(_$RadarBundleImpl) then) =
      __$$RadarBundleImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {List<TrendingMatch> trending,
      List<MarketMovement> movements,
      List<CommunitySignalCard> signals});
}

/// @nodoc
class __$$RadarBundleImplCopyWithImpl<$Res>
    extends _$RadarBundleCopyWithImpl<$Res, _$RadarBundleImpl>
    implements _$$RadarBundleImplCopyWith<$Res> {
  __$$RadarBundleImplCopyWithImpl(
      _$RadarBundleImpl _value, $Res Function(_$RadarBundleImpl) _then)
      : super(_value, _then);

  /// Create a copy of RadarBundle
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? trending = null,
    Object? movements = null,
    Object? signals = null,
  }) {
    return _then(_$RadarBundleImpl(
      trending: null == trending
          ? _value._trending
          : trending // ignore: cast_nullable_to_non_nullable
              as List<TrendingMatch>,
      movements: null == movements
          ? _value._movements
          : movements // ignore: cast_nullable_to_non_nullable
              as List<MarketMovement>,
      signals: null == signals
          ? _value._signals
          : signals // ignore: cast_nullable_to_non_nullable
              as List<CommunitySignalCard>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$RadarBundleImpl implements _RadarBundle {
  const _$RadarBundleImpl(
      {required final List<TrendingMatch> trending,
      required final List<MarketMovement> movements,
      required final List<CommunitySignalCard> signals})
      : _trending = trending,
        _movements = movements,
        _signals = signals;

  factory _$RadarBundleImpl.fromJson(Map<String, dynamic> json) =>
      _$$RadarBundleImplFromJson(json);

  final List<TrendingMatch> _trending;
  @override
  List<TrendingMatch> get trending {
    if (_trending is EqualUnmodifiableListView) return _trending;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_trending);
  }

  final List<MarketMovement> _movements;
  @override
  List<MarketMovement> get movements {
    if (_movements is EqualUnmodifiableListView) return _movements;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_movements);
  }

  final List<CommunitySignalCard> _signals;
  @override
  List<CommunitySignalCard> get signals {
    if (_signals is EqualUnmodifiableListView) return _signals;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_signals);
  }

  @override
  String toString() {
    return 'RadarBundle(trending: $trending, movements: $movements, signals: $signals)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$RadarBundleImpl &&
            const DeepCollectionEquality().equals(other._trending, _trending) &&
            const DeepCollectionEquality()
                .equals(other._movements, _movements) &&
            const DeepCollectionEquality().equals(other._signals, _signals));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      const DeepCollectionEquality().hash(_trending),
      const DeepCollectionEquality().hash(_movements),
      const DeepCollectionEquality().hash(_signals));

  /// Create a copy of RadarBundle
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$RadarBundleImplCopyWith<_$RadarBundleImpl> get copyWith =>
      __$$RadarBundleImplCopyWithImpl<_$RadarBundleImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$RadarBundleImplToJson(
      this,
    );
  }
}

abstract class _RadarBundle implements RadarBundle {
  const factory _RadarBundle(
      {required final List<TrendingMatch> trending,
      required final List<MarketMovement> movements,
      required final List<CommunitySignalCard> signals}) = _$RadarBundleImpl;

  factory _RadarBundle.fromJson(Map<String, dynamic> json) =
      _$RadarBundleImpl.fromJson;

  @override
  List<TrendingMatch> get trending;
  @override
  List<MarketMovement> get movements;
  @override
  List<CommunitySignalCard> get signals;

  /// Create a copy of RadarBundle
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$RadarBundleImplCopyWith<_$RadarBundleImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
