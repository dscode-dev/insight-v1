// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'match.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

MatchScore _$MatchScoreFromJson(Map<String, dynamic> json) {
  return _MatchScore.fromJson(json);
}

/// @nodoc
mixin _$MatchScore {
  int get home => throw _privateConstructorUsedError;
  int get away => throw _privateConstructorUsedError;

  /// Serializes this MatchScore to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchScore
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchScoreCopyWith<MatchScore> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchScoreCopyWith<$Res> {
  factory $MatchScoreCopyWith(
          MatchScore value, $Res Function(MatchScore) then) =
      _$MatchScoreCopyWithImpl<$Res, MatchScore>;
  @useResult
  $Res call({int home, int away});
}

/// @nodoc
class _$MatchScoreCopyWithImpl<$Res, $Val extends MatchScore>
    implements $MatchScoreCopyWith<$Res> {
  _$MatchScoreCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchScore
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? home = null,
    Object? away = null,
  }) {
    return _then(_value.copyWith(
      home: null == home
          ? _value.home
          : home // ignore: cast_nullable_to_non_nullable
              as int,
      away: null == away
          ? _value.away
          : away // ignore: cast_nullable_to_non_nullable
              as int,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$MatchScoreImplCopyWith<$Res>
    implements $MatchScoreCopyWith<$Res> {
  factory _$$MatchScoreImplCopyWith(
          _$MatchScoreImpl value, $Res Function(_$MatchScoreImpl) then) =
      __$$MatchScoreImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({int home, int away});
}

/// @nodoc
class __$$MatchScoreImplCopyWithImpl<$Res>
    extends _$MatchScoreCopyWithImpl<$Res, _$MatchScoreImpl>
    implements _$$MatchScoreImplCopyWith<$Res> {
  __$$MatchScoreImplCopyWithImpl(
      _$MatchScoreImpl _value, $Res Function(_$MatchScoreImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchScore
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? home = null,
    Object? away = null,
  }) {
    return _then(_$MatchScoreImpl(
      home: null == home
          ? _value.home
          : home // ignore: cast_nullable_to_non_nullable
              as int,
      away: null == away
          ? _value.away
          : away // ignore: cast_nullable_to_non_nullable
              as int,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchScoreImpl implements _MatchScore {
  const _$MatchScoreImpl({required this.home, required this.away});

  factory _$MatchScoreImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchScoreImplFromJson(json);

  @override
  final int home;
  @override
  final int away;

  @override
  String toString() {
    return 'MatchScore(home: $home, away: $away)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchScoreImpl &&
            (identical(other.home, home) || other.home == home) &&
            (identical(other.away, away) || other.away == away));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, home, away);

  /// Create a copy of MatchScore
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchScoreImplCopyWith<_$MatchScoreImpl> get copyWith =>
      __$$MatchScoreImplCopyWithImpl<_$MatchScoreImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchScoreImplToJson(
      this,
    );
  }
}

abstract class _MatchScore implements MatchScore {
  const factory _MatchScore(
      {required final int home, required final int away}) = _$MatchScoreImpl;

  factory _MatchScore.fromJson(Map<String, dynamic> json) =
      _$MatchScoreImpl.fromJson;

  @override
  int get home;
  @override
  int get away;

  /// Create a copy of MatchScore
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchScoreImplCopyWith<_$MatchScoreImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchTeam _$MatchTeamFromJson(Map<String, dynamic> json) {
  return _MatchTeam.fromJson(json);
}

/// @nodoc
mixin _$MatchTeam {
  String get short => throw _privateConstructorUsedError;
  String get name => throw _privateConstructorUsedError;
  String get crestColor => throw _privateConstructorUsedError;

  /// Serializes this MatchTeam to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchTeam
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchTeamCopyWith<MatchTeam> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchTeamCopyWith<$Res> {
  factory $MatchTeamCopyWith(MatchTeam value, $Res Function(MatchTeam) then) =
      _$MatchTeamCopyWithImpl<$Res, MatchTeam>;
  @useResult
  $Res call({String short, String name, String crestColor});
}

/// @nodoc
class _$MatchTeamCopyWithImpl<$Res, $Val extends MatchTeam>
    implements $MatchTeamCopyWith<$Res> {
  _$MatchTeamCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchTeam
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? short = null,
    Object? name = null,
    Object? crestColor = null,
  }) {
    return _then(_value.copyWith(
      short: null == short
          ? _value.short
          : short // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      crestColor: null == crestColor
          ? _value.crestColor
          : crestColor // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$MatchTeamImplCopyWith<$Res>
    implements $MatchTeamCopyWith<$Res> {
  factory _$$MatchTeamImplCopyWith(
          _$MatchTeamImpl value, $Res Function(_$MatchTeamImpl) then) =
      __$$MatchTeamImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String short, String name, String crestColor});
}

/// @nodoc
class __$$MatchTeamImplCopyWithImpl<$Res>
    extends _$MatchTeamCopyWithImpl<$Res, _$MatchTeamImpl>
    implements _$$MatchTeamImplCopyWith<$Res> {
  __$$MatchTeamImplCopyWithImpl(
      _$MatchTeamImpl _value, $Res Function(_$MatchTeamImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchTeam
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? short = null,
    Object? name = null,
    Object? crestColor = null,
  }) {
    return _then(_$MatchTeamImpl(
      short: null == short
          ? _value.short
          : short // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      crestColor: null == crestColor
          ? _value.crestColor
          : crestColor // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchTeamImpl implements _MatchTeam {
  const _$MatchTeamImpl(
      {required this.short, required this.name, required this.crestColor});

  factory _$MatchTeamImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchTeamImplFromJson(json);

  @override
  final String short;
  @override
  final String name;
  @override
  final String crestColor;

  @override
  String toString() {
    return 'MatchTeam(short: $short, name: $name, crestColor: $crestColor)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchTeamImpl &&
            (identical(other.short, short) || other.short == short) &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.crestColor, crestColor) ||
                other.crestColor == crestColor));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, short, name, crestColor);

  /// Create a copy of MatchTeam
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchTeamImplCopyWith<_$MatchTeamImpl> get copyWith =>
      __$$MatchTeamImplCopyWithImpl<_$MatchTeamImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchTeamImplToJson(
      this,
    );
  }
}

abstract class _MatchTeam implements MatchTeam {
  const factory _MatchTeam(
      {required final String short,
      required final String name,
      required final String crestColor}) = _$MatchTeamImpl;

  factory _MatchTeam.fromJson(Map<String, dynamic> json) =
      _$MatchTeamImpl.fromJson;

  @override
  String get short;
  @override
  String get name;
  @override
  String get crestColor;

  /// Create a copy of MatchTeam
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchTeamImplCopyWith<_$MatchTeamImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchStatus _$MatchStatusFromJson(Map<String, dynamic> json) {
  return _MatchStatus.fromJson(json);
}

/// @nodoc
mixin _$MatchStatus {
  MatchState get state => throw _privateConstructorUsedError;
  int? get minute => throw _privateConstructorUsedError;
  String? get period => throw _privateConstructorUsedError;
  MatchScore? get score => throw _privateConstructorUsedError;
  DateTime get kickoff => throw _privateConstructorUsedError;

  /// Serializes this MatchStatus to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchStatus
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchStatusCopyWith<MatchStatus> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchStatusCopyWith<$Res> {
  factory $MatchStatusCopyWith(
          MatchStatus value, $Res Function(MatchStatus) then) =
      _$MatchStatusCopyWithImpl<$Res, MatchStatus>;
  @useResult
  $Res call(
      {MatchState state,
      int? minute,
      String? period,
      MatchScore? score,
      DateTime kickoff});

  $MatchScoreCopyWith<$Res>? get score;
}

/// @nodoc
class _$MatchStatusCopyWithImpl<$Res, $Val extends MatchStatus>
    implements $MatchStatusCopyWith<$Res> {
  _$MatchStatusCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchStatus
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? state = null,
    Object? minute = freezed,
    Object? period = freezed,
    Object? score = freezed,
    Object? kickoff = null,
  }) {
    return _then(_value.copyWith(
      state: null == state
          ? _value.state
          : state // ignore: cast_nullable_to_non_nullable
              as MatchState,
      minute: freezed == minute
          ? _value.minute
          : minute // ignore: cast_nullable_to_non_nullable
              as int?,
      period: freezed == period
          ? _value.period
          : period // ignore: cast_nullable_to_non_nullable
              as String?,
      score: freezed == score
          ? _value.score
          : score // ignore: cast_nullable_to_non_nullable
              as MatchScore?,
      kickoff: null == kickoff
          ? _value.kickoff
          : kickoff // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }

  /// Create a copy of MatchStatus
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchScoreCopyWith<$Res>? get score {
    if (_value.score == null) {
      return null;
    }

    return $MatchScoreCopyWith<$Res>(_value.score!, (value) {
      return _then(_value.copyWith(score: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$MatchStatusImplCopyWith<$Res>
    implements $MatchStatusCopyWith<$Res> {
  factory _$$MatchStatusImplCopyWith(
          _$MatchStatusImpl value, $Res Function(_$MatchStatusImpl) then) =
      __$$MatchStatusImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {MatchState state,
      int? minute,
      String? period,
      MatchScore? score,
      DateTime kickoff});

  @override
  $MatchScoreCopyWith<$Res>? get score;
}

/// @nodoc
class __$$MatchStatusImplCopyWithImpl<$Res>
    extends _$MatchStatusCopyWithImpl<$Res, _$MatchStatusImpl>
    implements _$$MatchStatusImplCopyWith<$Res> {
  __$$MatchStatusImplCopyWithImpl(
      _$MatchStatusImpl _value, $Res Function(_$MatchStatusImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchStatus
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? state = null,
    Object? minute = freezed,
    Object? period = freezed,
    Object? score = freezed,
    Object? kickoff = null,
  }) {
    return _then(_$MatchStatusImpl(
      state: null == state
          ? _value.state
          : state // ignore: cast_nullable_to_non_nullable
              as MatchState,
      minute: freezed == minute
          ? _value.minute
          : minute // ignore: cast_nullable_to_non_nullable
              as int?,
      period: freezed == period
          ? _value.period
          : period // ignore: cast_nullable_to_non_nullable
              as String?,
      score: freezed == score
          ? _value.score
          : score // ignore: cast_nullable_to_non_nullable
              as MatchScore?,
      kickoff: null == kickoff
          ? _value.kickoff
          : kickoff // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchStatusImpl implements _MatchStatus {
  const _$MatchStatusImpl(
      {required this.state,
      this.minute,
      this.period,
      this.score,
      required this.kickoff});

  factory _$MatchStatusImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchStatusImplFromJson(json);

  @override
  final MatchState state;
  @override
  final int? minute;
  @override
  final String? period;
  @override
  final MatchScore? score;
  @override
  final DateTime kickoff;

  @override
  String toString() {
    return 'MatchStatus(state: $state, minute: $minute, period: $period, score: $score, kickoff: $kickoff)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchStatusImpl &&
            (identical(other.state, state) || other.state == state) &&
            (identical(other.minute, minute) || other.minute == minute) &&
            (identical(other.period, period) || other.period == period) &&
            (identical(other.score, score) || other.score == score) &&
            (identical(other.kickoff, kickoff) || other.kickoff == kickoff));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, state, minute, period, score, kickoff);

  /// Create a copy of MatchStatus
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchStatusImplCopyWith<_$MatchStatusImpl> get copyWith =>
      __$$MatchStatusImplCopyWithImpl<_$MatchStatusImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchStatusImplToJson(
      this,
    );
  }
}

abstract class _MatchStatus implements MatchStatus {
  const factory _MatchStatus(
      {required final MatchState state,
      final int? minute,
      final String? period,
      final MatchScore? score,
      required final DateTime kickoff}) = _$MatchStatusImpl;

  factory _MatchStatus.fromJson(Map<String, dynamic> json) =
      _$MatchStatusImpl.fromJson;

  @override
  MatchState get state;
  @override
  int? get minute;
  @override
  String? get period;
  @override
  MatchScore? get score;
  @override
  DateTime get kickoff;

  /// Create a copy of MatchStatus
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchStatusImplCopyWith<_$MatchStatusImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

IntelligencePill _$IntelligencePillFromJson(Map<String, dynamic> json) {
  return _IntelligencePill.fromJson(json);
}

/// @nodoc
mixin _$IntelligencePill {
  String get label => throw _privateConstructorUsedError;
  IntelligencePillTone get tone => throw _privateConstructorUsedError;

  /// Serializes this IntelligencePill to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of IntelligencePill
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $IntelligencePillCopyWith<IntelligencePill> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $IntelligencePillCopyWith<$Res> {
  factory $IntelligencePillCopyWith(
          IntelligencePill value, $Res Function(IntelligencePill) then) =
      _$IntelligencePillCopyWithImpl<$Res, IntelligencePill>;
  @useResult
  $Res call({String label, IntelligencePillTone tone});
}

/// @nodoc
class _$IntelligencePillCopyWithImpl<$Res, $Val extends IntelligencePill>
    implements $IntelligencePillCopyWith<$Res> {
  _$IntelligencePillCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of IntelligencePill
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
              as IntelligencePillTone,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$IntelligencePillImplCopyWith<$Res>
    implements $IntelligencePillCopyWith<$Res> {
  factory _$$IntelligencePillImplCopyWith(_$IntelligencePillImpl value,
          $Res Function(_$IntelligencePillImpl) then) =
      __$$IntelligencePillImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({String label, IntelligencePillTone tone});
}

/// @nodoc
class __$$IntelligencePillImplCopyWithImpl<$Res>
    extends _$IntelligencePillCopyWithImpl<$Res, _$IntelligencePillImpl>
    implements _$$IntelligencePillImplCopyWith<$Res> {
  __$$IntelligencePillImplCopyWithImpl(_$IntelligencePillImpl _value,
      $Res Function(_$IntelligencePillImpl) _then)
      : super(_value, _then);

  /// Create a copy of IntelligencePill
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? label = null,
    Object? tone = null,
  }) {
    return _then(_$IntelligencePillImpl(
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      tone: null == tone
          ? _value.tone
          : tone // ignore: cast_nullable_to_non_nullable
              as IntelligencePillTone,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$IntelligencePillImpl implements _IntelligencePill {
  const _$IntelligencePillImpl({required this.label, required this.tone});

  factory _$IntelligencePillImpl.fromJson(Map<String, dynamic> json) =>
      _$$IntelligencePillImplFromJson(json);

  @override
  final String label;
  @override
  final IntelligencePillTone tone;

  @override
  String toString() {
    return 'IntelligencePill(label: $label, tone: $tone)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$IntelligencePillImpl &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.tone, tone) || other.tone == tone));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, label, tone);

  /// Create a copy of IntelligencePill
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$IntelligencePillImplCopyWith<_$IntelligencePillImpl> get copyWith =>
      __$$IntelligencePillImplCopyWithImpl<_$IntelligencePillImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$IntelligencePillImplToJson(
      this,
    );
  }
}

abstract class _IntelligencePill implements IntelligencePill {
  const factory _IntelligencePill(
      {required final String label,
      required final IntelligencePillTone tone}) = _$IntelligencePillImpl;

  factory _IntelligencePill.fromJson(Map<String, dynamic> json) =
      _$IntelligencePillImpl.fromJson;

  @override
  String get label;
  @override
  IntelligencePillTone get tone;

  /// Create a copy of IntelligencePill
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$IntelligencePillImplCopyWith<_$IntelligencePillImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

MatchSummary _$MatchSummaryFromJson(Map<String, dynamic> json) {
  return _MatchSummary.fromJson(json);
}

/// @nodoc
mixin _$MatchSummary {
  String get matchId => throw _privateConstructorUsedError;
  String get league => throw _privateConstructorUsedError;
  MatchTeam get home => throw _privateConstructorUsedError;
  MatchTeam get away => throw _privateConstructorUsedError;
  MatchStatus get status => throw _privateConstructorUsedError;
  List<IntelligencePill> get pills => throw _privateConstructorUsedError;

  /// Serializes this MatchSummary to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $MatchSummaryCopyWith<MatchSummary> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $MatchSummaryCopyWith<$Res> {
  factory $MatchSummaryCopyWith(
          MatchSummary value, $Res Function(MatchSummary) then) =
      _$MatchSummaryCopyWithImpl<$Res, MatchSummary>;
  @useResult
  $Res call(
      {String matchId,
      String league,
      MatchTeam home,
      MatchTeam away,
      MatchStatus status,
      List<IntelligencePill> pills});

  $MatchTeamCopyWith<$Res> get home;
  $MatchTeamCopyWith<$Res> get away;
  $MatchStatusCopyWith<$Res> get status;
}

/// @nodoc
class _$MatchSummaryCopyWithImpl<$Res, $Val extends MatchSummary>
    implements $MatchSummaryCopyWith<$Res> {
  _$MatchSummaryCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? matchId = null,
    Object? league = null,
    Object? home = null,
    Object? away = null,
    Object? status = null,
    Object? pills = null,
  }) {
    return _then(_value.copyWith(
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      league: null == league
          ? _value.league
          : league // ignore: cast_nullable_to_non_nullable
              as String,
      home: null == home
          ? _value.home
          : home // ignore: cast_nullable_to_non_nullable
              as MatchTeam,
      away: null == away
          ? _value.away
          : away // ignore: cast_nullable_to_non_nullable
              as MatchTeam,
      status: null == status
          ? _value.status
          : status // ignore: cast_nullable_to_non_nullable
              as MatchStatus,
      pills: null == pills
          ? _value.pills
          : pills // ignore: cast_nullable_to_non_nullable
              as List<IntelligencePill>,
    ) as $Val);
  }

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchTeamCopyWith<$Res> get home {
    return $MatchTeamCopyWith<$Res>(_value.home, (value) {
      return _then(_value.copyWith(home: value) as $Val);
    });
  }

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchTeamCopyWith<$Res> get away {
    return $MatchTeamCopyWith<$Res>(_value.away, (value) {
      return _then(_value.copyWith(away: value) as $Val);
    });
  }

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $MatchStatusCopyWith<$Res> get status {
    return $MatchStatusCopyWith<$Res>(_value.status, (value) {
      return _then(_value.copyWith(status: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$MatchSummaryImplCopyWith<$Res>
    implements $MatchSummaryCopyWith<$Res> {
  factory _$$MatchSummaryImplCopyWith(
          _$MatchSummaryImpl value, $Res Function(_$MatchSummaryImpl) then) =
      __$$MatchSummaryImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String matchId,
      String league,
      MatchTeam home,
      MatchTeam away,
      MatchStatus status,
      List<IntelligencePill> pills});

  @override
  $MatchTeamCopyWith<$Res> get home;
  @override
  $MatchTeamCopyWith<$Res> get away;
  @override
  $MatchStatusCopyWith<$Res> get status;
}

/// @nodoc
class __$$MatchSummaryImplCopyWithImpl<$Res>
    extends _$MatchSummaryCopyWithImpl<$Res, _$MatchSummaryImpl>
    implements _$$MatchSummaryImplCopyWith<$Res> {
  __$$MatchSummaryImplCopyWithImpl(
      _$MatchSummaryImpl _value, $Res Function(_$MatchSummaryImpl) _then)
      : super(_value, _then);

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? matchId = null,
    Object? league = null,
    Object? home = null,
    Object? away = null,
    Object? status = null,
    Object? pills = null,
  }) {
    return _then(_$MatchSummaryImpl(
      matchId: null == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String,
      league: null == league
          ? _value.league
          : league // ignore: cast_nullable_to_non_nullable
              as String,
      home: null == home
          ? _value.home
          : home // ignore: cast_nullable_to_non_nullable
              as MatchTeam,
      away: null == away
          ? _value.away
          : away // ignore: cast_nullable_to_non_nullable
              as MatchTeam,
      status: null == status
          ? _value.status
          : status // ignore: cast_nullable_to_non_nullable
              as MatchStatus,
      pills: null == pills
          ? _value._pills
          : pills // ignore: cast_nullable_to_non_nullable
              as List<IntelligencePill>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$MatchSummaryImpl implements _MatchSummary {
  const _$MatchSummaryImpl(
      {required this.matchId,
      required this.league,
      required this.home,
      required this.away,
      required this.status,
      final List<IntelligencePill> pills = const <IntelligencePill>[]})
      : _pills = pills;

  factory _$MatchSummaryImpl.fromJson(Map<String, dynamic> json) =>
      _$$MatchSummaryImplFromJson(json);

  @override
  final String matchId;
  @override
  final String league;
  @override
  final MatchTeam home;
  @override
  final MatchTeam away;
  @override
  final MatchStatus status;
  final List<IntelligencePill> _pills;
  @override
  @JsonKey()
  List<IntelligencePill> get pills {
    if (_pills is EqualUnmodifiableListView) return _pills;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_pills);
  }

  @override
  String toString() {
    return 'MatchSummary(matchId: $matchId, league: $league, home: $home, away: $away, status: $status, pills: $pills)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$MatchSummaryImpl &&
            (identical(other.matchId, matchId) || other.matchId == matchId) &&
            (identical(other.league, league) || other.league == league) &&
            (identical(other.home, home) || other.home == home) &&
            (identical(other.away, away) || other.away == away) &&
            (identical(other.status, status) || other.status == status) &&
            const DeepCollectionEquality().equals(other._pills, _pills));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, matchId, league, home, away,
      status, const DeepCollectionEquality().hash(_pills));

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$MatchSummaryImplCopyWith<_$MatchSummaryImpl> get copyWith =>
      __$$MatchSummaryImplCopyWithImpl<_$MatchSummaryImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$MatchSummaryImplToJson(
      this,
    );
  }
}

abstract class _MatchSummary implements MatchSummary {
  const factory _MatchSummary(
      {required final String matchId,
      required final String league,
      required final MatchTeam home,
      required final MatchTeam away,
      required final MatchStatus status,
      final List<IntelligencePill> pills}) = _$MatchSummaryImpl;

  factory _MatchSummary.fromJson(Map<String, dynamic> json) =
      _$MatchSummaryImpl.fromJson;

  @override
  String get matchId;
  @override
  String get league;
  @override
  MatchTeam get home;
  @override
  MatchTeam get away;
  @override
  MatchStatus get status;
  @override
  List<IntelligencePill> get pills;

  /// Create a copy of MatchSummary
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$MatchSummaryImplCopyWith<_$MatchSummaryImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
