// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'match_context.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

MatchContextSignal _$MatchContextSignalFromJson(Map<String, dynamic> json) {
  return _MatchContextSignal.fromJson(json);
}

/// @nodoc
mixin _$MatchContextSignal {
  String get label => throw _privateConstructorUsedError;
  SignalDirection get direction => throw _privateConstructorUsedError;

  /// Serializes this MatchContextSignal to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchContextSignal
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchContextSignalCopyWith<MatchContextSignal> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchContextSignalCopyWith<$Res> {
  factory $MatchContextSignalCopyWith(
          MatchContextSignal value, $Res Function(MatchContextSignal) then) =
      _$MatchContextSignalCopyWithImpl<$Res, MatchContextSignal>;
  @useResult
  $Res call({String label, SignalDirection direction});
}

/// @nodoc
class _$MatchContextSignalCopyWithImpl<$Res, $Val extends MatchContextSignal>
    implements $MatchContextSignalCopyWith<$Res> {
  _$MatchContextSignalCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchContextSignal
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? label = null,
    Object? direction = null,
  }) {
    return _then(_value.copyWith(
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      direction: null == direction
          ? _value.direction
          : direction // ignore: cast_nullable_to_non_nullable
              as SignalDirection,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$MatchContextSignalImplCopyWith<$Res>
    implements $MatchContextSignalCopyWith<$Res> {
  factory _$$MatchContextSignalImplCopyWith(_$MatchContextSignalImpl value,
          $Res Function(_$MatchContextSignalImpl) then) =
      __$$MatchContextSignalImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String label, SignalDirection direction});
}

/// @nodoc
class __$$MatchContextSignalImplCopyWithImpl<$Res>
    extends _$MatchContextSignalCopyWithImpl<$Res, _$MatchContextSignalImpl>
    implements _$$MatchContextSignalImplCopyWith<$Res> {
  __$$MatchContextSignalImplCopyWithImpl(_$MatchContextSignalImpl _value,
      $Res Function(_$MatchContextSignalImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchContextSignal
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? label = null,
    Object? direction = null,
  }) {
    return _then(_$MatchContextSignalImpl(
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      direction: null == direction
          ? _value.direction
          : direction // ignore: cast_nullable_to_non_nullable
              as SignalDirection,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchContextSignalImpl implements _MatchContextSignal {
  const _$MatchContextSignalImpl(
      {required this.label, this.direction = SignalDirection.neutral});

  factory _$MatchContextSignalImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchContextSignalImplFromJson(json);

  @override
  final String label;
  @override
  @JsonKey()
  final SignalDirection direction;

  @override
  String toString() {
    return 'MatchContextSignal(label: $label, direction: $direction)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchContextSignalImpl &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.direction, direction) ||
                other.direction == direction));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, label, direction);

  /// Create a copy of MatchContextSignal
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchContextSignalImplCopyWith<_$MatchContextSignalImpl> get copyWith =>
      __$$MatchContextSignalImplCopyWithImpl<_$MatchContextSignalImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchContextSignalImplToJson(
      this,
    );
  }
}

abstract class _MatchContextSignal implements MatchContextSignal {
  const factory _MatchContextSignal(
      {required final String label,
      final SignalDirection direction}) = _$MatchContextSignalImpl;

  factory _MatchContextSignal.fromJson(Map<String, dynamic> json) =
      _$MatchContextSignalImpl.fromJson;

  @override
  String get label;
  @override
  SignalDirection get direction;

  /// Create a copy of MatchContextSignal
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchContextSignalImplCopyWith<_$MatchContextSignalImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchProbabilities _$MatchProbabilitiesFromJson(Map<String, dynamic> json) {
  return _MatchProbabilities.fromJson(json);
}

/// @nodoc
mixin _$MatchProbabilities {
  double get home => throw _privateConstructorUsedError;
  double get draw => throw _privateConstructorUsedError;
  double get away => throw _privateConstructorUsedError;

  /// Serializes this MatchProbabilities to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchProbabilities
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchProbabilitiesCopyWith<MatchProbabilities> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchProbabilitiesCopyWith<$Res> {
  factory $MatchProbabilitiesCopyWith(
          MatchProbabilities value, $Res Function(MatchProbabilities) then) =
      _$MatchProbabilitiesCopyWithImpl<$Res, MatchProbabilities>;
  @useResult
  $Res call({double home, double draw, double away});
}

/// @nodoc
class _$MatchProbabilitiesCopyWithImpl<$Res, $Val extends MatchProbabilities>
    implements $MatchProbabilitiesCopyWith<$Res> {
  _$MatchProbabilitiesCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchProbabilities
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? home = null,
    Object? draw = null,
    Object? away = null,
  }) {
    return _then(_value.copyWith(
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
abstract class _$$MatchProbabilitiesImplCopyWith<$Res>
    implements $MatchProbabilitiesCopyWith<$Res> {
  factory _$$MatchProbabilitiesImplCopyWith(_$MatchProbabilitiesImpl value,
          $Res Function(_$MatchProbabilitiesImpl) then) =
      __$$MatchProbabilitiesImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({double home, double draw, double away});
}

/// @nodoc
class __$$MatchProbabilitiesImplCopyWithImpl<$Res>
    extends _$MatchProbabilitiesCopyWithImpl<$Res, _$MatchProbabilitiesImpl>
    implements _$$MatchProbabilitiesImplCopyWith<$Res> {
  __$$MatchProbabilitiesImplCopyWithImpl(_$MatchProbabilitiesImpl _value,
      $Res Function(_$MatchProbabilitiesImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchProbabilities
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? home = null,
    Object? draw = null,
    Object? away = null,
  }) {
    return _then(_$MatchProbabilitiesImpl(
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
class _$MatchProbabilitiesImpl implements _MatchProbabilities {
  const _$MatchProbabilitiesImpl(
      {required this.home, required this.draw, required this.away});

  factory _$MatchProbabilitiesImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchProbabilitiesImplFromJson(json);

  @override
  final double home;
  @override
  final double draw;
  @override
  final double away;

  @override
  String toString() {
    return 'MatchProbabilities(home: $home, draw: $draw, away: $away)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchProbabilitiesImpl &&
            (identical(other.home, home) || other.home == home) &&
            (identical(other.draw, draw) || other.draw == draw) &&
            (identical(other.away, away) || other.away == away));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, home, draw, away);

  /// Create a copy of MatchProbabilities
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchProbabilitiesImplCopyWith<_$MatchProbabilitiesImpl> get copyWith =>
      __$$MatchProbabilitiesImplCopyWithImpl<_$MatchProbabilitiesImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchProbabilitiesImplToJson(
      this,
    );
  }
}

abstract class _MatchProbabilities implements MatchProbabilities {
  const factory _MatchProbabilities(
      {required final double home,
      required final double draw,
      required final double away}) = _$MatchProbabilitiesImpl;

  factory _MatchProbabilities.fromJson(Map<String, dynamic> json) =
      _$MatchProbabilitiesImpl.fromJson;

  @override
  double get home;
  @override
  double get draw;
  @override
  double get away;

  /// Create a copy of MatchProbabilities
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchProbabilitiesImplCopyWith<_$MatchProbabilitiesImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchContextReading _$MatchContextReadingFromJson(Map<String, dynamic> json) {
  return _MatchContextReading.fromJson(json);
}

/// @nodoc
mixin _$MatchContextReading {
  String get matchId => throw _privateConstructorUsedError;
  List<MatchContextSignal> get signals => throw _privateConstructorUsedError;
  MatchProbabilities? get probabilities => throw _privateConstructorUsedError;

  /// Serializes this MatchContextReading to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchContextReading
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchContextReadingCopyWith<MatchContextReading> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchContextReadingCopyWith<$Res> {
  factory $MatchContextReadingCopyWith(
          MatchContextReading value, $Res Function(MatchContextReading) then) =
      _$MatchContextReadingCopyWithImpl<$Res, MatchContextReading>;
  @useResult
  $Res call(
      {String matchId,
      List<MatchContextSignal> signals,
      MatchProbabilities? probabilities});

  $MatchProbabilitiesCopyWith<$Res>? get probabilities;
}

/// @nodoc
class _$MatchContextReadingCopyWithImpl<$Res, $Val extends MatchContextReading>
    implements $MatchContextReadingCopyWith<$Res> {
  _$MatchContextReadingCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchContextReading
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? matchId = null,
    Object? signals = null,
    Object? probabilities = freezed,
  }) {
    return _then(_value.copyWith(
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as List<MatchContextSignal>,
      probabilities: freezed == probabilities
          ? _value.probabilities
          : probabilities // ignore: cast_nullable_to_non_nullable
              as MatchProbabilities?,
    ) as $Val);
  }

  /// Create a copy of MatchContextReading
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchProbabilitiesCopyWith<$Res>? get probabilities {
    if (_value.probabilities == null) {
      return null;
    }

    return $MatchProbabilitiesCopyWith<$Res>(_value.probabilities!, (value) {
      return _then(_value.copyWith(probabilities: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$MatchContextReadingImplCopyWith<$Res>
    implements $MatchContextReadingCopyWith<$Res> {
  factory _$$MatchContextReadingImplCopyWith(_$MatchContextReadingImpl value,
          $Res Function(_$MatchContextReadingImpl) then) =
      __$$MatchContextReadingImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String matchId,
      List<MatchContextSignal> signals,
      MatchProbabilities? probabilities});

  @override
  $MatchProbabilitiesCopyWith<$Res>? get probabilities;
}

/// @nodoc
class __$$MatchContextReadingImplCopyWithImpl<$Res>
    extends _$MatchContextReadingCopyWithImpl<$Res, _$MatchContextReadingImpl>
    implements _$$MatchContextReadingImplCopyWith<$Res> {
  __$$MatchContextReadingImplCopyWithImpl(_$MatchContextReadingImpl _value,
      $Res Function(_$MatchContextReadingImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchContextReading
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? matchId = null,
    Object? signals = null,
    Object? probabilities = freezed,
  }) {
    return _then(_$MatchContextReadingImpl(
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      signals: null == signals
          ? _value._signals
          : signals // ignore: cast_nullable_to_non_nullable
              as List<MatchContextSignal>,
      probabilities: freezed == probabilities
          ? _value.probabilities
          : probabilities // ignore: cast_nullable_to_non_nullable
              as MatchProbabilities?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchContextReadingImpl implements _MatchContextReading {
  const _$MatchContextReadingImpl(
      {required this.matchId,
      final List<MatchContextSignal> signals = const <MatchContextSignal>[],
      this.probabilities})
      : _signals = signals;

  factory _$MatchContextReadingImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchContextReadingImplFromJson(json);

  @override
  final String matchId;
  final List<MatchContextSignal> _signals;
  @override
  @JsonKey()
  List<MatchContextSignal> get signals {
    if (_signals is EqualUnmodifiableListView) return _signals;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_signals);
  }

  @override
  final MatchProbabilities? probabilities;

  @override
  String toString() {
    return 'MatchContextReading(matchId: $matchId, signals: $signals, probabilities: $probabilities)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchContextReadingImpl &&
            (identical(other.matchId, matchId) || other.matchId == matchId) &&
            const DeepCollectionEquality().equals(other._signals, _signals) &&
            (identical(other.probabilities, probabilities) ||
                other.probabilities == probabilities));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, matchId,
      const DeepCollectionEquality().hash(_signals), probabilities);

  /// Create a copy of MatchContextReading
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchContextReadingImplCopyWith<_$MatchContextReadingImpl> get copyWith =>
      __$$MatchContextReadingImplCopyWithImpl<_$MatchContextReadingImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchContextReadingImplToJson(
      this,
    );
  }
}

abstract class _MatchContextReading implements MatchContextReading {
  const factory _MatchContextReading(
      {required final String matchId,
      final List<MatchContextSignal> signals,
      final MatchProbabilities? probabilities}) = _$MatchContextReadingImpl;

  factory _MatchContextReading.fromJson(Map<String, dynamic> json) =
      _$MatchContextReadingImpl.fromJson;

  @override
  String get matchId;
  @override
  List<MatchContextSignal> get signals;
  @override
  MatchProbabilities? get probabilities;

  /// Create a copy of MatchContextReading
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchContextReadingImplCopyWith<_$MatchContextReadingImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
