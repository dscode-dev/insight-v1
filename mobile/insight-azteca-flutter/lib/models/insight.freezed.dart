// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'insight.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

AgentInsight _$AgentInsightFromJson(Map<String, dynamic> json) {
  return _AgentInsight.fromJson(json);
}

/// @nodoc
mixin _$AgentInsight {
  String get insightId => throw _privateConstructorUsedError;
  AgentId get agentId => throw _privateConstructorUsedError;
  AgentInsightKind get insightKind => throw _privateConstructorUsedError;
  String get matchId => throw _privateConstructorUsedError;
  String get headline => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  double get confidence => throw _privateConstructorUsedError;
  int? get minute => throw _privateConstructorUsedError;
  List<String> get refs => throw _privateConstructorUsedError;
  Map<String, dynamic> get metrics => throw _privateConstructorUsedError;
  DateTime get createdAt => throw _privateConstructorUsedError;

  /// Serializes this AgentInsight to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of AgentInsight
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $AgentInsightCopyWith<AgentInsight> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $AgentInsightCopyWith<$Res> {
  factory $AgentInsightCopyWith(
          AgentInsight value, $Res Function(AgentInsight) then) =
      _$AgentInsightCopyWithImpl<$Res, AgentInsight>;
  @useResult
  $Res call(
      {String insightId,
      AgentId agentId,
      AgentInsightKind insightKind,
      String matchId,
      String headline,
      String body,
      double confidence,
      int? minute,
      List<String> refs,
      Map<String, dynamic> metrics,
      DateTime createdAt});
}

/// @nodoc
class _$AgentInsightCopyWithImpl<$Res, $Val extends AgentInsight>
    implements $AgentInsightCopyWith<$Res> {
  _$AgentInsightCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of AgentInsight
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? insightId = null,
    Object? agentId = null,
    Object? insightKind = null,
    Object? matchId = null,
    Object? headline = null,
    Object? body = null,
    Object? confidence = null,
    Object? minute = freezed,
    Object? refs = null,
    Object? metrics = null,
    Object? createdAt = null,
  }) {
    return _then(_value.copyWith(
      insightId: null == insightId
          ? _value.insightId
          : insightId // ignore: cast_nullable_to_non_nullable
              as String,
      agentId: null == agentId
          ? _value.agentId
          : agentId // ignore: cast_nullable_to_non_nullable
              as AgentId,
      insightKind: null == insightKind
          ? _value.insightKind
          : insightKind // ignore: cast_nullable_to_non_nullable
              as AgentInsightKind,
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      headline: null == headline
          ? _value.headline
          : headline // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      confidence: null == confidence
          ? _value.confidence
          : confidence // ignore: cast_nullable_to_non_nullable
              as double,
      minute: freezed == minute
          ? _value.minute
          : minute // ignore: cast_nullable_to_non_nullable
              as int?,
      refs: null == refs
          ? _value.refs
          : refs // ignore: cast_nullable_to_non_nullable
              as List<String>,
      metrics: null == metrics
          ? _value.metrics
          : metrics // ignore: cast_nullable_to_non_nullable
              as Map<String, dynamic>,
      createdAt: null == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$AgentInsightImplCopyWith<$Res>
    implements $AgentInsightCopyWith<$Res> {
  factory _$$AgentInsightImplCopyWith(
          _$AgentInsightImpl value, $Res Function(_$AgentInsightImpl) then) =
      __$$AgentInsightImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String insightId,
      AgentId agentId,
      AgentInsightKind insightKind,
      String matchId,
      String headline,
      String body,
      double confidence,
      int? minute,
      List<String> refs,
      Map<String, dynamic> metrics,
      DateTime createdAt});
}

/// @nodoc
class __$$AgentInsightImplCopyWithImpl<$Res>
    extends _$AgentInsightCopyWithImpl<$Res, _$AgentInsightImpl>
    implements _$$AgentInsightImplCopyWith<$Res> {
  __$$AgentInsightImplCopyWithImpl(
      _$AgentInsightImpl _value, $Res Function(_$AgentInsightImpl) _then)
      : super(_value, _then);

  /// Create a copy of AgentInsight
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? insightId = null,
    Object? agentId = null,
    Object? insightKind = null,
    Object? matchId = null,
    Object? headline = null,
    Object? body = null,
    Object? confidence = null,
    Object? minute = freezed,
    Object? refs = null,
    Object? metrics = null,
    Object? createdAt = null,
  }) {
    return _then(_$AgentInsightImpl(
      insightId: null == insightId
          ? _value.insightId
          : insightId // ignore: cast_nullable_to_non_nullable
              as String,
      agentId: null == agentId
          ? _value.agentId
          : agentId // ignore: cast_nullable_to_non_nullable
              as AgentId,
      insightKind: null == insightKind
          ? _value.insightKind
          : insightKind // ignore: cast_nullable_to_non_nullable
              as AgentInsightKind,
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      headline: null == headline
          ? _value.headline
          : headline // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      confidence: null == confidence
          ? _value.confidence
          : confidence // ignore: cast_nullable_to_non_nullable
              as double,
      minute: freezed == minute
          ? _value.minute
          : minute // ignore: cast_nullable_to_non_nullable
              as int?,
      refs: null == refs
          ? _value._refs
          : refs // ignore: cast_nullable_to_non_nullable
              as List<String>,
      metrics: null == metrics
          ? _value._metrics
          : metrics // ignore: cast_nullable_to_non_nullable
              as Map<String, dynamic>,
      createdAt: null == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$AgentInsightImpl implements _AgentInsight {
  const _$AgentInsightImpl(
      {required this.insightId,
      required this.agentId,
      required this.insightKind,
      required this.matchId,
      required this.headline,
      this.body = '',
      required this.confidence,
      this.minute,
      final List<String> refs = const <String>[],
      final Map<String, dynamic> metrics = const <String, dynamic>{},
      required this.createdAt})
      : _refs = refs,
        _metrics = metrics;

  factory _$AgentInsightImpl.fromJson(Map<String, dynamic> json) =>
      _$$AgentInsightImplFromJson(json);

  @override
  final String insightId;
  @override
  final AgentId agentId;
  @override
  final AgentInsightKind insightKind;
  @override
  final String matchId;
  @override
  final String headline;
  @override
  @JsonKey()
  final String body;
  @override
  final double confidence;
  @override
  final int? minute;
  final List<String> _refs;
  @override
  @JsonKey()
  List<String> get refs {
    if (_refs is EqualUnmodifiableListView) return _refs;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_refs);
  }

  final Map<String, dynamic> _metrics;
  @override
  @JsonKey()
  Map<String, dynamic> get metrics {
    if (_metrics is EqualUnmodifiableMapView) return _metrics;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableMapView(_metrics);
  }

  @override
  final DateTime createdAt;

  @override
  String toString() {
    return 'AgentInsight(insightId: $insightId, agentId: $agentId, insightKind: $insightKind, matchId: $matchId, headline: $headline, body: $body, confidence: $confidence, minute: $minute, refs: $refs, metrics: $metrics, createdAt: $createdAt)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$AgentInsightImpl &&
            (identical(other.insightId, insightId) ||
                other.insightId == insightId) &&
            (identical(other.agentId, agentId) || other.agentId == agentId) &&
            (identical(other.insightKind, insightKind) ||
                other.insightKind == insightKind) &&
            (identical(other.matchId, matchId) || other.matchId == matchId) &&
            (identical(other.headline, headline) ||
                other.headline == headline) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.confidence, confidence) ||
                other.confidence == confidence) &&
            (identical(other.minute, minute) || other.minute == minute) &&
            const DeepCollectionEquality().equals(other._refs, _refs) &&
            const DeepCollectionEquality().equals(other._metrics, _metrics) &&
            (identical(other.createdAt, createdAt) ||
                other.createdAt == createdAt));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      insightId,
      agentId,
      insightKind,
      matchId,
      headline,
      body,
      confidence,
      minute,
      const DeepCollectionEquality().hash(_refs),
      const DeepCollectionEquality().hash(_metrics),
      createdAt);

  /// Create a copy of AgentInsight
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$AgentInsightImplCopyWith<_$AgentInsightImpl> get copyWith =>
      __$$AgentInsightImplCopyWithImpl<_$AgentInsightImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$AgentInsightImplToJson(
      this,
    );
  }
}

abstract class _AgentInsight implements AgentInsight {
  const factory _AgentInsight(
      {required final String insightId,
      required final AgentId agentId,
      required final AgentInsightKind insightKind,
      required final String matchId,
      required final String headline,
      final String body,
      required final double confidence,
      final int? minute,
      final List<String> refs,
      final Map<String, dynamic> metrics,
      required final DateTime createdAt}) = _$AgentInsightImpl;

  factory _AgentInsight.fromJson(Map<String, dynamic> json) =
      _$AgentInsightImpl.fromJson;

  @override
  String get insightId;
  @override
  AgentId get agentId;
  @override
  AgentInsightKind get insightKind;
  @override
  String get matchId;
  @override
  String get headline;
  @override
  String get body;
  @override
  double get confidence;
  @override
  int? get minute;
  @override
  List<String> get refs;
  @override
  Map<String, dynamic> get metrics;
  @override
  DateTime get createdAt;

  /// Create a copy of AgentInsight
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$AgentInsightImplCopyWith<_$AgentInsightImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
