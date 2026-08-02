// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'live.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

LiveFilter _$LiveFilterFromJson(Map<String, dynamic> json) {
  return _LiveFilter.fromJson(json);
}

/// @nodoc
mixin _$LiveFilter {
  String? get competitionId => throw _privateConstructorUsedError;
  LiveStatusFilter get status => throw _privateConstructorUsedError;

  /// Serializes this LiveFilter to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LiveFilter
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LiveFilterCopyWith<LiveFilter> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LiveFilterCopyWith<$Res> {
  factory $LiveFilterCopyWith(
          LiveFilter value, $Res Function(LiveFilter) then) =
      _$LiveFilterCopyWithImpl<$Res, LiveFilter>;
  @useResult
  $Res call({String? competitionId, LiveStatusFilter status});
}

/// @nodoc
class _$LiveFilterCopyWithImpl<$Res, $Val extends LiveFilter>
    implements $LiveFilterCopyWith<$Res> {
  _$LiveFilterCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LiveFilter
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? competitionId = freezed,
    Object? status = null,
  }) {
    return _then(_value.copyWith(
      competitionId: freezed == competitionId
          ? _value.competitionId
          : competitionId // ignore: cast_nullable_to_non_nullable
              as String?,
      status: null == status
          ? _value.status
          : status // ignore: cast_nullable_to_non_nullable
              as LiveStatusFilter,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$LiveFilterImplCopyWith<$Res>
    implements $LiveFilterCopyWith<$Res> {
  factory _$$LiveFilterImplCopyWith(
          _$LiveFilterImpl value, $Res Function(_$LiveFilterImpl) then) =
      __$$LiveFilterImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String? competitionId, LiveStatusFilter status});
}

/// @nodoc
class __$$LiveFilterImplCopyWithImpl<$Res>
    extends _$LiveFilterCopyWithImpl<$Res, _$LiveFilterImpl>
    implements _$$LiveFilterImplCopyWith<$Res> {
  __$$LiveFilterImplCopyWithImpl(
      _$LiveFilterImpl _value, $Res Function(_$LiveFilterImpl) _then)
      : super(_value, _then);

  /// Create a copy of LiveFilter
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? competitionId = freezed,
    Object? status = null,
  }) {
    return _then(_$LiveFilterImpl(
      competitionId: freezed == competitionId
          ? _value.competitionId
          : competitionId // ignore: cast_nullable_to_non_nullable
              as String?,
      status: null == status
          ? _value.status
          : status // ignore: cast_nullable_to_non_nullable
              as LiveStatusFilter,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$LiveFilterImpl implements _LiveFilter {
  const _$LiveFilterImpl(
      {this.competitionId, this.status = LiveStatusFilter.all});

  factory _$LiveFilterImpl.fromJson(Map<String, dynamic> json) =>
      _$$LiveFilterImplFromJson(json);

  @override
  final String? competitionId;
  @override
  @JsonKey()
  final LiveStatusFilter status;

  @override
  String toString() {
    return 'LiveFilter(competitionId: $competitionId, status: $status)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LiveFilterImpl &&
            (identical(other.competitionId, competitionId) ||
                other.competitionId == competitionId) &&
            (identical(other.status, status) || other.status == status));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, competitionId, status);

  /// Create a copy of LiveFilter
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LiveFilterImplCopyWith<_$LiveFilterImpl> get copyWith =>
      __$$LiveFilterImplCopyWithImpl<_$LiveFilterImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$LiveFilterImplToJson(
      this,
    );
  }
}

abstract class _LiveFilter implements LiveFilter {
  const factory _LiveFilter(
      {final String? competitionId,
      final LiveStatusFilter status}) = _$LiveFilterImpl;

  factory _LiveFilter.fromJson(Map<String, dynamic> json) =
      _$LiveFilterImpl.fromJson;

  @override
  String? get competitionId;
  @override
  LiveStatusFilter get status;

  /// Create a copy of LiveFilter
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LiveFilterImplCopyWith<_$LiveFilterImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

LiveMatch _$LiveMatchFromJson(Map<String, dynamic> json) {
  return _LiveMatch.fromJson(json);
}

/// @nodoc
mixin _$LiveMatch {
  MatchSummary get summary => throw _privateConstructorUsedError;

  /// -1..1 — negative favours away, positive favours home.
  double get momentum => throw _privateConstructorUsedError;

  /// 0..1 — current pressure intensity (composite).
  double get pressure => throw _privateConstructorUsedError;

  /// Serializes this LiveMatch to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of LiveMatch
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $LiveMatchCopyWith<LiveMatch> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $LiveMatchCopyWith<$Res> {
  factory $LiveMatchCopyWith(LiveMatch value, $Res Function(LiveMatch) then) =
      _$LiveMatchCopyWithImpl<$Res, LiveMatch>;
  @useResult
  $Res call({MatchSummary summary, double momentum, double pressure});

  $MatchSummaryCopyWith<$Res> get summary;
}

/// @nodoc
class _$LiveMatchCopyWithImpl<$Res, $Val extends LiveMatch>
    implements $LiveMatchCopyWith<$Res> {
  _$LiveMatchCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of LiveMatch
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? summary = null,
    Object? momentum = null,
    Object? pressure = null,
  }) {
    return _then(_value.copyWith(
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as MatchSummary,
      momentum: null == momentum
          ? _value.momentum
          : momentum // ignore: cast_nullable_to_non_nullable
              as double,
      pressure: null == pressure
          ? _value.pressure
          : pressure // ignore: cast_nullable_to_non_nullable
              as double,
    ) as $Val);
  }

  /// Create a copy of LiveMatch
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
abstract class _$$LiveMatchImplCopyWith<$Res>
    implements $LiveMatchCopyWith<$Res> {
  factory _$$LiveMatchImplCopyWith(
          _$LiveMatchImpl value, $Res Function(_$LiveMatchImpl) then) =
      __$$LiveMatchImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({MatchSummary summary, double momentum, double pressure});

  @override
  $MatchSummaryCopyWith<$Res> get summary;
}

/// @nodoc
class __$$LiveMatchImplCopyWithImpl<$Res>
    extends _$LiveMatchCopyWithImpl<$Res, _$LiveMatchImpl>
    implements _$$LiveMatchImplCopyWith<$Res> {
  __$$LiveMatchImplCopyWithImpl(
      _$LiveMatchImpl _value, $Res Function(_$LiveMatchImpl) _then)
      : super(_value, _then);

  /// Create a copy of LiveMatch
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? summary = null,
    Object? momentum = null,
    Object? pressure = null,
  }) {
    return _then(_$LiveMatchImpl(
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as MatchSummary,
      momentum: null == momentum
          ? _value.momentum
          : momentum // ignore: cast_nullable_to_non_nullable
              as double,
      pressure: null == pressure
          ? _value.pressure
          : pressure // ignore: cast_nullable_to_non_nullable
              as double,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$LiveMatchImpl implements _LiveMatch {
  const _$LiveMatchImpl(
      {required this.summary, required this.momentum, required this.pressure});

  factory _$LiveMatchImpl.fromJson(Map<String, dynamic> json) =>
      _$$LiveMatchImplFromJson(json);

  @override
  final MatchSummary summary;

  /// -1..1 — negative favours away, positive favours home.
  @override
  final double momentum;

  /// 0..1 — current pressure intensity (composite).
  @override
  final double pressure;

  @override
  String toString() {
    return 'LiveMatch(summary: $summary, momentum: $momentum, pressure: $pressure)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$LiveMatchImpl &&
            (identical(other.summary, summary) || other.summary == summary) &&
            (identical(other.momentum, momentum) ||
                other.momentum == momentum) &&
            (identical(other.pressure, pressure) ||
                other.pressure == pressure));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, summary, momentum, pressure);

  /// Create a copy of LiveMatch
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$LiveMatchImplCopyWith<_$LiveMatchImpl> get copyWith =>
      __$$LiveMatchImplCopyWithImpl<_$LiveMatchImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$LiveMatchImplToJson(
      this,
    );
  }
}

abstract class _LiveMatch implements LiveMatch {
  const factory _LiveMatch(
      {required final MatchSummary summary,
      required final double momentum,
      required final double pressure}) = _$LiveMatchImpl;

  factory _LiveMatch.fromJson(Map<String, dynamic> json) =
      _$LiveMatchImpl.fromJson;

  @override
  MatchSummary get summary;

  /// -1..1 — negative favours away, positive favours home.
  @override
  double get momentum;

  /// 0..1 — current pressure intensity (composite).
  @override
  double get pressure;

  /// Create a copy of LiveMatch
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$LiveMatchImplCopyWith<_$LiveMatchImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

TimelinePoint _$TimelinePointFromJson(Map<String, dynamic> json) {
  return _TimelinePoint.fromJson(json);
}

/// @nodoc
mixin _$TimelinePoint {
  DateTime get ts => throw _privateConstructorUsedError;
  double get value => throw _privateConstructorUsedError;

  /// Serializes this TimelinePoint to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of TimelinePoint
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TimelinePointCopyWith<TimelinePoint> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TimelinePointCopyWith<$Res> {
  factory $TimelinePointCopyWith(
          TimelinePoint value, $Res Function(TimelinePoint) then) =
      _$TimelinePointCopyWithImpl<$Res, TimelinePoint>;
  @useResult
  $Res call({DateTime ts, double value});
}

/// @nodoc
class _$TimelinePointCopyWithImpl<$Res, $Val extends TimelinePoint>
    implements $TimelinePointCopyWith<$Res> {
  _$TimelinePointCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of TimelinePoint
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? ts = null,
    Object? value = null,
  }) {
    return _then(_value.copyWith(
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
      value: null == value
          ? _value.value
          : value // ignore: cast_nullable_to_non_nullable
              as double,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$TimelinePointImplCopyWith<$Res>
    implements $TimelinePointCopyWith<$Res> {
  factory _$$TimelinePointImplCopyWith(
          _$TimelinePointImpl value, $Res Function(_$TimelinePointImpl) then) =
      __$$TimelinePointImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({DateTime ts, double value});
}

/// @nodoc
class __$$TimelinePointImplCopyWithImpl<$Res>
    extends _$TimelinePointCopyWithImpl<$Res, _$TimelinePointImpl>
    implements _$$TimelinePointImplCopyWith<$Res> {
  __$$TimelinePointImplCopyWithImpl(
      _$TimelinePointImpl _value, $Res Function(_$TimelinePointImpl) _then)
      : super(_value, _then);

  /// Create a copy of TimelinePoint
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? ts = null,
    Object? value = null,
  }) {
    return _then(_$TimelinePointImpl(
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
      value: null == value
          ? _value.value
          : value // ignore: cast_nullable_to_non_nullable
              as double,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$TimelinePointImpl implements _TimelinePoint {
  const _$TimelinePointImpl({required this.ts, required this.value});

  factory _$TimelinePointImpl.fromJson(Map<String, dynamic> json) =>
      _$$TimelinePointImplFromJson(json);

  @override
  final DateTime ts;
  @override
  final double value;

  @override
  String toString() {
    return 'TimelinePoint(ts: $ts, value: $value)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TimelinePointImpl &&
            (identical(other.ts, ts) || other.ts == ts) &&
            (identical(other.value, value) || other.value == value));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, ts, value);

  /// Create a copy of TimelinePoint
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TimelinePointImplCopyWith<_$TimelinePointImpl> get copyWith =>
      __$$TimelinePointImplCopyWithImpl<_$TimelinePointImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$TimelinePointImplToJson(
      this,
    );
  }
}

abstract class _TimelinePoint implements TimelinePoint {
  const factory _TimelinePoint(
      {required final DateTime ts,
      required final double value}) = _$TimelinePointImpl;

  factory _TimelinePoint.fromJson(Map<String, dynamic> json) =
      _$TimelinePointImpl.fromJson;

  @override
  DateTime get ts;
  @override
  double get value;

  /// Create a copy of TimelinePoint
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TimelinePointImplCopyWith<_$TimelinePointImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

OddsPoint _$OddsPointFromJson(Map<String, dynamic> json) {
  return _OddsPoint.fromJson(json);
}

/// @nodoc
mixin _$OddsPoint {
  DateTime get ts => throw _privateConstructorUsedError;
  double get home => throw _privateConstructorUsedError;
  double get draw => throw _privateConstructorUsedError;
  double get away => throw _privateConstructorUsedError;

  /// Serializes this OddsPoint to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of OddsPoint
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $OddsPointCopyWith<OddsPoint> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $OddsPointCopyWith<$Res> {
  factory $OddsPointCopyWith(OddsPoint value, $Res Function(OddsPoint) then) =
      _$OddsPointCopyWithImpl<$Res, OddsPoint>;
  @useResult
  $Res call({DateTime ts, double home, double draw, double away});
}

/// @nodoc
class _$OddsPointCopyWithImpl<$Res, $Val extends OddsPoint>
    implements $OddsPointCopyWith<$Res> {
  _$OddsPointCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of OddsPoint
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? ts = null,
    Object? home = null,
    Object? draw = null,
    Object? away = null,
  }) {
    return _then(_value.copyWith(
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
      home: null == home
          ? _value.home
          : home // ignore: cast_nullable_to_non_nullable
              as double,
      draw: null == draw
          ? _value.draw
          : draw // ignore: cast_nullable_to_non_nullable
              as double,
      away: null == away
          ? _value.away
          : away // ignore: cast_nullable_to_non_nullable
              as double,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$OddsPointImplCopyWith<$Res>
    implements $OddsPointCopyWith<$Res> {
  factory _$$OddsPointImplCopyWith(
          _$OddsPointImpl value, $Res Function(_$OddsPointImpl) then) =
      __$$OddsPointImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({DateTime ts, double home, double draw, double away});
}

/// @nodoc
class __$$OddsPointImplCopyWithImpl<$Res>
    extends _$OddsPointCopyWithImpl<$Res, _$OddsPointImpl>
    implements _$$OddsPointImplCopyWith<$Res> {
  __$$OddsPointImplCopyWithImpl(
      _$OddsPointImpl _value, $Res Function(_$OddsPointImpl) _then)
      : super(_value, _then);

  /// Create a copy of OddsPoint
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? ts = null,
    Object? home = null,
    Object? draw = null,
    Object? away = null,
  }) {
    return _then(_$OddsPointImpl(
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
      home: null == home
          ? _value.home
          : home // ignore: cast_nullable_to_non_nullable
              as double,
      draw: null == draw
          ? _value.draw
          : draw // ignore: cast_nullable_to_non_nullable
              as double,
      away: null == away
          ? _value.away
          : away // ignore: cast_nullable_to_non_nullable
              as double,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$OddsPointImpl implements _OddsPoint {
  const _$OddsPointImpl(
      {required this.ts,
      required this.home,
      required this.draw,
      required this.away});

  factory _$OddsPointImpl.fromJson(Map<String, dynamic> json) =>
      _$$OddsPointImplFromJson(json);

  @override
  final DateTime ts;
  @override
  final double home;
  @override
  final double draw;
  @override
  final double away;

  @override
  String toString() {
    return 'OddsPoint(ts: $ts, home: $home, draw: $draw, away: $away)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$OddsPointImpl &&
            (identical(other.ts, ts) || other.ts == ts) &&
            (identical(other.home, home) || other.home == home) &&
            (identical(other.draw, draw) || other.draw == draw) &&
            (identical(other.away, away) || other.away == away));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, ts, home, draw, away);

  /// Create a copy of OddsPoint
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$OddsPointImplCopyWith<_$OddsPointImpl> get copyWith =>
      __$$OddsPointImplCopyWithImpl<_$OddsPointImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$OddsPointImplToJson(
      this,
    );
  }
}

abstract class _OddsPoint implements OddsPoint {
  const factory _OddsPoint(
      {required final DateTime ts,
      required final double home,
      required final double draw,
      required final double away}) = _$OddsPointImpl;

  factory _OddsPoint.fromJson(Map<String, dynamic> json) =
      _$OddsPointImpl.fromJson;

  @override
  DateTime get ts;
  @override
  double get home;
  @override
  double get draw;
  @override
  double get away;

  /// Create a copy of OddsPoint
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$OddsPointImplCopyWith<_$OddsPointImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchSignal _$MatchSignalFromJson(Map<String, dynamic> json) {
  return _MatchSignal.fromJson(json);
}

/// @nodoc
mixin _$MatchSignal {
  String get id => throw _privateConstructorUsedError;
  String get source =>
      throw _privateConstructorUsedError; // model | expert | community
  String get label => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  DateTime get ts => throw _privateConstructorUsedError;

  /// Serializes this MatchSignal to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchSignal
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchSignalCopyWith<MatchSignal> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchSignalCopyWith<$Res> {
  factory $MatchSignalCopyWith(
          MatchSignal value, $Res Function(MatchSignal) then) =
      _$MatchSignalCopyWithImpl<$Res, MatchSignal>;
  @useResult
  $Res call({String id, String source, String label, String body, DateTime ts});
}

/// @nodoc
class _$MatchSignalCopyWithImpl<$Res, $Val extends MatchSignal>
    implements $MatchSignalCopyWith<$Res> {
  _$MatchSignalCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchSignal
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? source = null,
    Object? label = null,
    Object? body = null,
    Object? ts = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      source: null == source
          ? _value.source
          : source // ignore: cast_nullable_to_non_nullable
              as String,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$MatchSignalImplCopyWith<$Res>
    implements $MatchSignalCopyWith<$Res> {
  factory _$$MatchSignalImplCopyWith(
          _$MatchSignalImpl value, $Res Function(_$MatchSignalImpl) then) =
      __$$MatchSignalImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String id, String source, String label, String body, DateTime ts});
}

/// @nodoc
class __$$MatchSignalImplCopyWithImpl<$Res>
    extends _$MatchSignalCopyWithImpl<$Res, _$MatchSignalImpl>
    implements _$$MatchSignalImplCopyWith<$Res> {
  __$$MatchSignalImplCopyWithImpl(
      _$MatchSignalImpl _value, $Res Function(_$MatchSignalImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchSignal
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? source = null,
    Object? label = null,
    Object? body = null,
    Object? ts = null,
  }) {
    return _then(_$MatchSignalImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      source: null == source
          ? _value.source
          : source // ignore: cast_nullable_to_non_nullable
              as String,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      ts: null == ts
          ? _value.ts
          : ts // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchSignalImpl implements _MatchSignal {
  const _$MatchSignalImpl(
      {required this.id,
      required this.source,
      required this.label,
      required this.body,
      required this.ts});

  factory _$MatchSignalImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchSignalImplFromJson(json);

  @override
  final String id;
  @override
  final String source;
// model | expert | community
  @override
  final String label;
  @override
  final String body;
  @override
  final DateTime ts;

  @override
  String toString() {
    return 'MatchSignal(id: $id, source: $source, label: $label, body: $body, ts: $ts)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchSignalImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.source, source) || other.source == source) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.ts, ts) || other.ts == ts));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, source, label, body, ts);

  /// Create a copy of MatchSignal
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchSignalImplCopyWith<_$MatchSignalImpl> get copyWith =>
      __$$MatchSignalImplCopyWithImpl<_$MatchSignalImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchSignalImplToJson(
      this,
    );
  }
}

abstract class _MatchSignal implements MatchSignal {
  const factory _MatchSignal(
      {required final String id,
      required final String source,
      required final String label,
      required final String body,
      required final DateTime ts}) = _$MatchSignalImpl;

  factory _MatchSignal.fromJson(Map<String, dynamic> json) =
      _$MatchSignalImpl.fromJson;

  @override
  String get id;
  @override
  String get source; // model | expert | community
  @override
  String get label;
  @override
  String get body;
  @override
  DateTime get ts;

  /// Create a copy of MatchSignal
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchSignalImplCopyWith<_$MatchSignalImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchDetail _$MatchDetailFromJson(Map<String, dynamic> json) {
  return _MatchDetail.fromJson(json);
}

/// @nodoc
mixin _$MatchDetail {
  MatchSummary get summary => throw _privateConstructorUsedError;
  List<OddsPoint> get oddsTimeline => throw _privateConstructorUsedError;
  List<TimelinePoint> get pressureTimeline =>
      throw _privateConstructorUsedError;
  List<MatchSignal> get signals => throw _privateConstructorUsedError;

  /// Serializes this MatchDetail to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchDetail
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchDetailCopyWith<MatchDetail> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchDetailCopyWith<$Res> {
  factory $MatchDetailCopyWith(
          MatchDetail value, $Res Function(MatchDetail) then) =
      _$MatchDetailCopyWithImpl<$Res, MatchDetail>;
  @useResult
  $Res call(
      {MatchSummary summary,
      List<OddsPoint> oddsTimeline,
      List<TimelinePoint> pressureTimeline,
      List<MatchSignal> signals});

  $MatchSummaryCopyWith<$Res> get summary;
}

/// @nodoc
class _$MatchDetailCopyWithImpl<$Res, $Val extends MatchDetail>
    implements $MatchDetailCopyWith<$Res> {
  _$MatchDetailCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchDetail
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? summary = null,
    Object? oddsTimeline = null,
    Object? pressureTimeline = null,
    Object? signals = null,
  }) {
    return _then(_value.copyWith(
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as MatchSummary,
      oddsTimeline: null == oddsTimeline
          ? _value.oddsTimeline
          : oddsTimeline // ignore: cast_nullable_to_non_nullable
              as List<OddsPoint>,
      pressureTimeline: null == pressureTimeline
          ? _value.pressureTimeline
          : pressureTimeline // ignore: cast_nullable_to_non_nullable
              as List<TimelinePoint>,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as List<MatchSignal>,
    ) as $Val);
  }

  /// Create a copy of MatchDetail
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
abstract class _$$MatchDetailImplCopyWith<$Res>
    implements $MatchDetailCopyWith<$Res> {
  factory _$$MatchDetailImplCopyWith(
          _$MatchDetailImpl value, $Res Function(_$MatchDetailImpl) then) =
      __$$MatchDetailImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {MatchSummary summary,
      List<OddsPoint> oddsTimeline,
      List<TimelinePoint> pressureTimeline,
      List<MatchSignal> signals});

  @override
  $MatchSummaryCopyWith<$Res> get summary;
}

/// @nodoc
class __$$MatchDetailImplCopyWithImpl<$Res>
    extends _$MatchDetailCopyWithImpl<$Res, _$MatchDetailImpl>
    implements _$$MatchDetailImplCopyWith<$Res> {
  __$$MatchDetailImplCopyWithImpl(
      _$MatchDetailImpl _value, $Res Function(_$MatchDetailImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchDetail
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? summary = null,
    Object? oddsTimeline = null,
    Object? pressureTimeline = null,
    Object? signals = null,
  }) {
    return _then(_$MatchDetailImpl(
      summary: null == summary
          ? _value.summary
          : summary // ignore: cast_nullable_to_non_nullable
              as MatchSummary,
      oddsTimeline: null == oddsTimeline
          ? _value._oddsTimeline
          : oddsTimeline // ignore: cast_nullable_to_non_nullable
              as List<OddsPoint>,
      pressureTimeline: null == pressureTimeline
          ? _value._pressureTimeline
          : pressureTimeline // ignore: cast_nullable_to_non_nullable
              as List<TimelinePoint>,
      signals: null == signals
          ? _value._signals
          : signals // ignore: cast_nullable_to_non_nullable
              as List<MatchSignal>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchDetailImpl implements _MatchDetail {
  const _$MatchDetailImpl(
      {required this.summary,
      final List<OddsPoint> oddsTimeline = const <OddsPoint>[],
      final List<TimelinePoint> pressureTimeline = const <TimelinePoint>[],
      final List<MatchSignal> signals = const <MatchSignal>[]})
      : _oddsTimeline = oddsTimeline,
        _pressureTimeline = pressureTimeline,
        _signals = signals;

  factory _$MatchDetailImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchDetailImplFromJson(json);

  @override
  final MatchSummary summary;
  final List<OddsPoint> _oddsTimeline;
  @override
  @JsonKey()
  List<OddsPoint> get oddsTimeline {
    if (_oddsTimeline is EqualUnmodifiableListView) return _oddsTimeline;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_oddsTimeline);
  }

  final List<TimelinePoint> _pressureTimeline;
  @override
  @JsonKey()
  List<TimelinePoint> get pressureTimeline {
    if (_pressureTimeline is EqualUnmodifiableListView)
      return _pressureTimeline;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_pressureTimeline);
  }

  final List<MatchSignal> _signals;
  @override
  @JsonKey()
  List<MatchSignal> get signals {
    if (_signals is EqualUnmodifiableListView) return _signals;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_signals);
  }

  @override
  String toString() {
    return 'MatchDetail(summary: $summary, oddsTimeline: $oddsTimeline, pressureTimeline: $pressureTimeline, signals: $signals)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchDetailImpl &&
            (identical(other.summary, summary) || other.summary == summary) &&
            const DeepCollectionEquality()
                .equals(other._oddsTimeline, _oddsTimeline) &&
            const DeepCollectionEquality()
                .equals(other._pressureTimeline, _pressureTimeline) &&
            const DeepCollectionEquality().equals(other._signals, _signals));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      summary,
      const DeepCollectionEquality().hash(_oddsTimeline),
      const DeepCollectionEquality().hash(_pressureTimeline),
      const DeepCollectionEquality().hash(_signals));

  /// Create a copy of MatchDetail
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchDetailImplCopyWith<_$MatchDetailImpl> get copyWith =>
      __$$MatchDetailImplCopyWithImpl<_$MatchDetailImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchDetailImplToJson(
      this,
    );
  }
}

abstract class _MatchDetail implements MatchDetail {
  const factory _MatchDetail(
      {required final MatchSummary summary,
      final List<OddsPoint> oddsTimeline,
      final List<TimelinePoint> pressureTimeline,
      final List<MatchSignal> signals}) = _$MatchDetailImpl;

  factory _MatchDetail.fromJson(Map<String, dynamic> json) =
      _$MatchDetailImpl.fromJson;

  @override
  MatchSummary get summary;
  @override
  List<OddsPoint> get oddsTimeline;
  @override
  List<TimelinePoint> get pressureTimeline;
  @override
  List<MatchSignal> get signals;

  /// Create a copy of MatchDetail
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchDetailImplCopyWith<_$MatchDetailImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
