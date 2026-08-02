// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'profile.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

UserStats _$UserStatsFromJson(Map<String, dynamic> json) {
  return _UserStats.fromJson(json);
}

/// @nodoc
mixin _$UserStats {
  int get reputation => throw _privateConstructorUsedError; // 0..100
  int get posts => throw _privateConstructorUsedError;
  int get signals => throw _privateConstructorUsedError;
  double get accuracy => throw _privateConstructorUsedError;

  /// Serializes this UserStats to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of UserStats
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $UserStatsCopyWith<UserStats> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $UserStatsCopyWith<$Res> {
  factory $UserStatsCopyWith(UserStats value, $Res Function(UserStats) then) =
      _$UserStatsCopyWithImpl<$Res, UserStats>;
  @useResult
  $Res call({int reputation, int posts, int signals, double accuracy});
}

/// @nodoc
class _$UserStatsCopyWithImpl<$Res, $Val extends UserStats>
    implements $UserStatsCopyWith<$Res> {
  _$UserStatsCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of UserStats
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? reputation = null,
    Object? posts = null,
    Object? signals = null,
    Object? accuracy = null,
  }) {
    return _then(_value.copyWith(
      reputation: null == reputation
          ? _value.reputation
          : reputation // ignore: cast_nullable_to_non_nullable
              as int,
      posts: null == posts
          ? _value.posts
          : posts // ignore: cast_nullable_to_non_nullable
              as int,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as int,
      accuracy: null == accuracy
          ? _value.accuracy
          : accuracy // ignore: cast_nullable_to_non_nullable
              as double,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$UserStatsImplCopyWith<$Res>
    implements $UserStatsCopyWith<$Res> {
  factory _$$UserStatsImplCopyWith(
          _$UserStatsImpl value, $Res Function(_$UserStatsImpl) then) =
      __$$UserStatsImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({int reputation, int posts, int signals, double accuracy});
}

/// @nodoc
class __$$UserStatsImplCopyWithImpl<$Res>
    extends _$UserStatsCopyWithImpl<$Res, _$UserStatsImpl>
    implements _$$UserStatsImplCopyWith<$Res> {
  __$$UserStatsImplCopyWithImpl(
      _$UserStatsImpl _value, $Res Function(_$UserStatsImpl) _then)
      : super(_value, _then);

  /// Create a copy of UserStats
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? reputation = null,
    Object? posts = null,
    Object? signals = null,
    Object? accuracy = null,
  }) {
    return _then(_$UserStatsImpl(
      reputation: null == reputation
          ? _value.reputation
          : reputation // ignore: cast_nullable_to_non_nullable
              as int,
      posts: null == posts
          ? _value.posts
          : posts // ignore: cast_nullable_to_non_nullable
              as int,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as int,
      accuracy: null == accuracy
          ? _value.accuracy
          : accuracy // ignore: cast_nullable_to_non_nullable
              as double,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$UserStatsImpl implements _UserStats {
  const _$UserStatsImpl(
      {required this.reputation,
      required this.posts,
      required this.signals,
      required this.accuracy});

  factory _$UserStatsImpl.fromJson(Map<String, dynamic> json) =>
      _$$UserStatsImplFromJson(json);

  @override
  final int reputation;
// 0..100
  @override
  final int posts;
  @override
  final int signals;
  @override
  final double accuracy;

  @override
  String toString() {
    return 'UserStats(reputation: $reputation, posts: $posts, signals: $signals, accuracy: $accuracy)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$UserStatsImpl &&
            (identical(other.reputation, reputation) ||
                other.reputation == reputation) &&
            (identical(other.posts, posts) || other.posts == posts) &&
            (identical(other.signals, signals) || other.signals == signals) &&
            (identical(other.accuracy, accuracy) ||
                other.accuracy == accuracy));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, reputation, posts, signals, accuracy);

  /// Create a copy of UserStats
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$UserStatsImplCopyWith<_$UserStatsImpl> get copyWith =>
      __$$UserStatsImplCopyWithImpl<_$UserStatsImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$UserStatsImplToJson(
      this,
    );
  }
}

abstract class _UserStats implements UserStats {
  const factory _UserStats(
      {required final int reputation,
      required final int posts,
      required final int signals,
      required final double accuracy}) = _$UserStatsImpl;

  factory _UserStats.fromJson(Map<String, dynamic> json) =
      _$UserStatsImpl.fromJson;

  @override
  int get reputation; // 0..100
  @override
  int get posts;
  @override
  int get signals;
  @override
  double get accuracy;

  /// Create a copy of UserStats
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$UserStatsImplCopyWith<_$UserStatsImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

UserBadge _$UserBadgeFromJson(Map<String, dynamic> json) {
  return _UserBadge.fromJson(json);
}

/// @nodoc
mixin _$UserBadge {
  String get id => throw _privateConstructorUsedError;
  String get label => throw _privateConstructorUsedError;
  String get description => throw _privateConstructorUsedError;
  String get emoji => throw _privateConstructorUsedError;
  DateTime get earnedAt => throw _privateConstructorUsedError;

  /// Serializes this UserBadge to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of UserBadge
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $UserBadgeCopyWith<UserBadge> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $UserBadgeCopyWith<$Res> {
  factory $UserBadgeCopyWith(UserBadge value, $Res Function(UserBadge) then) =
      _$UserBadgeCopyWithImpl<$Res, UserBadge>;
  @useResult
  $Res call(
      {String id,
      String label,
      String description,
      String emoji,
      DateTime earnedAt});
}

/// @nodoc
class _$UserBadgeCopyWithImpl<$Res, $Val extends UserBadge>
    implements $UserBadgeCopyWith<$Res> {
  _$UserBadgeCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of UserBadge
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? label = null,
    Object? description = null,
    Object? emoji = null,
    Object? earnedAt = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      description: null == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String,
      emoji: null == emoji
          ? _value.emoji
          : emoji // ignore: cast_nullable_to_non_nullable
              as String,
      earnedAt: null == earnedAt
          ? _value.earnedAt
          : earnedAt // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$UserBadgeImplCopyWith<$Res>
    implements $UserBadgeCopyWith<$Res> {
  factory _$$UserBadgeImplCopyWith(
          _$UserBadgeImpl value, $Res Function(_$UserBadgeImpl) then) =
      __$$UserBadgeImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String label,
      String description,
      String emoji,
      DateTime earnedAt});
}

/// @nodoc
class __$$UserBadgeImplCopyWithImpl<$Res>
    extends _$UserBadgeCopyWithImpl<$Res, _$UserBadgeImpl>
    implements _$$UserBadgeImplCopyWith<$Res> {
  __$$UserBadgeImplCopyWithImpl(
      _$UserBadgeImpl _value, $Res Function(_$UserBadgeImpl) _then)
      : super(_value, _then);

  /// Create a copy of UserBadge
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? label = null,
    Object? description = null,
    Object? emoji = null,
    Object? earnedAt = null,
  }) {
    return _then(_$UserBadgeImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      label: null == label
          ? _value.label
          : label // ignore: cast_nullable_to_non_nullable
              as String,
      description: null == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String,
      emoji: null == emoji
          ? _value.emoji
          : emoji // ignore: cast_nullable_to_non_nullable
              as String,
      earnedAt: null == earnedAt
          ? _value.earnedAt
          : earnedAt // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$UserBadgeImpl implements _UserBadge {
  const _$UserBadgeImpl(
      {required this.id,
      required this.label,
      required this.description,
      required this.emoji,
      required this.earnedAt});

  factory _$UserBadgeImpl.fromJson(Map<String, dynamic> json) =>
      _$$UserBadgeImplFromJson(json);

  @override
  final String id;
  @override
  final String label;
  @override
  final String description;
  @override
  final String emoji;
  @override
  final DateTime earnedAt;

  @override
  String toString() {
    return 'UserBadge(id: $id, label: $label, description: $description, emoji: $emoji, earnedAt: $earnedAt)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$UserBadgeImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.label, label) || other.label == label) &&
            (identical(other.description, description) ||
                other.description == description) &&
            (identical(other.emoji, emoji) || other.emoji == emoji) &&
            (identical(other.earnedAt, earnedAt) ||
                other.earnedAt == earnedAt));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode =>
      Object.hash(runtimeType, id, label, description, emoji, earnedAt);

  /// Create a copy of UserBadge
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$UserBadgeImplCopyWith<_$UserBadgeImpl> get copyWith =>
      __$$UserBadgeImplCopyWithImpl<_$UserBadgeImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$UserBadgeImplToJson(
      this,
    );
  }
}

abstract class _UserBadge implements UserBadge {
  const factory _UserBadge(
      {required final String id,
      required final String label,
      required final String description,
      required final String emoji,
      required final DateTime earnedAt}) = _$UserBadgeImpl;

  factory _UserBadge.fromJson(Map<String, dynamic> json) =
      _$UserBadgeImpl.fromJson;

  @override
  String get id;
  @override
  String get label;
  @override
  String get description;
  @override
  String get emoji;
  @override
  DateTime get earnedAt;

  /// Create a copy of UserBadge
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$UserBadgeImplCopyWith<_$UserBadgeImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

ProfileActivity _$ProfileActivityFromJson(Map<String, dynamic> json) {
  return _ProfileActivity.fromJson(json);
}

/// @nodoc
mixin _$ProfileActivity {
  String get id => throw _privateConstructorUsedError;
  ProfileActivityKind get kind => throw _privateConstructorUsedError;
  String get title => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  DateTime get ts => throw _privateConstructorUsedError;

  /// Serializes this ProfileActivity to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of ProfileActivity
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $ProfileActivityCopyWith<ProfileActivity> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $ProfileActivityCopyWith<$Res> {
  factory $ProfileActivityCopyWith(
          ProfileActivity value, $Res Function(ProfileActivity) then) =
      _$ProfileActivityCopyWithImpl<$Res, ProfileActivity>;
  @useResult
  $Res call(
      {String id,
      ProfileActivityKind kind,
      String title,
      String body,
      DateTime ts});
}

/// @nodoc
class _$ProfileActivityCopyWithImpl<$Res, $Val extends ProfileActivity>
    implements $ProfileActivityCopyWith<$Res> {
  _$ProfileActivityCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of ProfileActivity
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? kind = null,
    Object? title = null,
    Object? body = null,
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
              as ProfileActivityKind,
      title: null == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
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
abstract class _$$ProfileActivityImplCopyWith<$Res>
    implements $ProfileActivityCopyWith<$Res> {
  factory _$$ProfileActivityImplCopyWith(_$ProfileActivityImpl value,
          $Res Function(_$ProfileActivityImpl) then) =
      __$$ProfileActivityImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      ProfileActivityKind kind,
      String title,
      String body,
      DateTime ts});
}

/// @nodoc
class __$$ProfileActivityImplCopyWithImpl<$Res>
    extends _$ProfileActivityCopyWithImpl<$Res, _$ProfileActivityImpl>
    implements _$$ProfileActivityImplCopyWith<$Res> {
  __$$ProfileActivityImplCopyWithImpl(
      _$ProfileActivityImpl _value, $Res Function(_$ProfileActivityImpl) _then)
      : super(_value, _then);

  /// Create a copy of ProfileActivity
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? kind = null,
    Object? title = null,
    Object? body = null,
    Object? ts = null,
  }) {
    return _then(_$ProfileActivityImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      kind: null == kind
          ? _value.kind
          : kind // ignore: cast_nullable_to_non_nullable
              as ProfileActivityKind,
      title: null == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
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
class _$ProfileActivityImpl implements _ProfileActivity {
  const _$ProfileActivityImpl(
      {required this.id,
      required this.kind,
      required this.title,
      required this.body,
      required this.ts});

  factory _$ProfileActivityImpl.fromJson(Map<String, dynamic> json) =>
      _$$ProfileActivityImplFromJson(json);

  @override
  final String id;
  @override
  final ProfileActivityKind kind;
  @override
  final String title;
  @override
  final String body;
  @override
  final DateTime ts;

  @override
  String toString() {
    return 'ProfileActivity(id: $id, kind: $kind, title: $title, body: $body, ts: $ts)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$ProfileActivityImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.kind, kind) || other.kind == kind) &&
            (identical(other.title, title) || other.title == title) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.ts, ts) || other.ts == ts));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, kind, title, body, ts);

  /// Create a copy of ProfileActivity
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$ProfileActivityImplCopyWith<_$ProfileActivityImpl> get copyWith =>
      __$$ProfileActivityImplCopyWithImpl<_$ProfileActivityImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$ProfileActivityImplToJson(
      this,
    );
  }
}

abstract class _ProfileActivity implements ProfileActivity {
  const factory _ProfileActivity(
      {required final String id,
      required final ProfileActivityKind kind,
      required final String title,
      required final String body,
      required final DateTime ts}) = _$ProfileActivityImpl;

  factory _ProfileActivity.fromJson(Map<String, dynamic> json) =
      _$ProfileActivityImpl.fromJson;

  @override
  String get id;
  @override
  ProfileActivityKind get kind;
  @override
  String get title;
  @override
  String get body;
  @override
  DateTime get ts;

  /// Create a copy of ProfileActivity
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$ProfileActivityImplCopyWith<_$ProfileActivityImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

ProfileBundle _$ProfileBundleFromJson(Map<String, dynamic> json) {
  return _ProfileBundle.fromJson(json);
}

/// @nodoc
mixin _$ProfileBundle {
  UserStats get stats => throw _privateConstructorUsedError;
  List<UserBadge> get badges => throw _privateConstructorUsedError;
  List<ProfileActivity> get activity => throw _privateConstructorUsedError;

  /// Serializes this ProfileBundle to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of ProfileBundle
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $ProfileBundleCopyWith<ProfileBundle> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $ProfileBundleCopyWith<$Res> {
  factory $ProfileBundleCopyWith(
          ProfileBundle value, $Res Function(ProfileBundle) then) =
      _$ProfileBundleCopyWithImpl<$Res, ProfileBundle>;
  @useResult
  $Res call(
      {UserStats stats,
      List<UserBadge> badges,
      List<ProfileActivity> activity});

  $UserStatsCopyWith<$Res> get stats;
}

/// @nodoc
class _$ProfileBundleCopyWithImpl<$Res, $Val extends ProfileBundle>
    implements $ProfileBundleCopyWith<$Res> {
  _$ProfileBundleCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of ProfileBundle
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? stats = null,
    Object? badges = null,
    Object? activity = null,
  }) {
    return _then(_value.copyWith(
      stats: null == stats
          ? _value.stats
          : stats // ignore: cast_nullable_to_non_nullable
              as UserStats,
      badges: null == badges
          ? _value.badges
          : badges // ignore: cast_nullable_to_non_nullable
              as List<UserBadge>,
      activity: null == activity
          ? _value.activity
          : activity // ignore: cast_nullable_to_non_nullable
              as List<ProfileActivity>,
    ) as $Val);
  }

  /// Create a copy of ProfileBundle
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $UserStatsCopyWith<$Res> get stats {
    return $UserStatsCopyWith<$Res>(_value.stats, (value) {
      return _then(_value.copyWith(stats: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$ProfileBundleImplCopyWith<$Res>
    implements $ProfileBundleCopyWith<$Res> {
  factory _$$ProfileBundleImplCopyWith(
          _$ProfileBundleImpl value, $Res Function(_$ProfileBundleImpl) then) =
      __$$ProfileBundleImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {UserStats stats,
      List<UserBadge> badges,
      List<ProfileActivity> activity});

  @override
  $UserStatsCopyWith<$Res> get stats;
}

/// @nodoc
class __$$ProfileBundleImplCopyWithImpl<$Res>
    extends _$ProfileBundleCopyWithImpl<$Res, _$ProfileBundleImpl>
    implements _$$ProfileBundleImplCopyWith<$Res> {
  __$$ProfileBundleImplCopyWithImpl(
      _$ProfileBundleImpl _value, $Res Function(_$ProfileBundleImpl) _then)
      : super(_value, _then);

  /// Create a copy of ProfileBundle
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? stats = null,
    Object? badges = null,
    Object? activity = null,
  }) {
    return _then(_$ProfileBundleImpl(
      stats: null == stats
          ? _value.stats
          : stats // ignore: cast_nullable_to_non_nullable
              as UserStats,
      badges: null == badges
          ? _value._badges
          : badges // ignore: cast_nullable_to_non_nullable
              as List<UserBadge>,
      activity: null == activity
          ? _value._activity
          : activity // ignore: cast_nullable_to_non_nullable
              as List<ProfileActivity>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$ProfileBundleImpl implements _ProfileBundle {
  const _$ProfileBundleImpl(
      {required this.stats,
      required final List<UserBadge> badges,
      required final List<ProfileActivity> activity})
      : _badges = badges,
        _activity = activity;

  factory _$ProfileBundleImpl.fromJson(Map<String, dynamic> json) =>
      _$$ProfileBundleImplFromJson(json);

  @override
  final UserStats stats;
  final List<UserBadge> _badges;
  @override
  List<UserBadge> get badges {
    if (_badges is EqualUnmodifiableListView) return _badges;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_badges);
  }

  final List<ProfileActivity> _activity;
  @override
  List<ProfileActivity> get activity {
    if (_activity is EqualUnmodifiableListView) return _activity;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_activity);
  }

  @override
  String toString() {
    return 'ProfileBundle(stats: $stats, badges: $badges, activity: $activity)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$ProfileBundleImpl &&
            (identical(other.stats, stats) || other.stats == stats) &&
            const DeepCollectionEquality().equals(other._badges, _badges) &&
            const DeepCollectionEquality().equals(other._activity, _activity));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      stats,
      const DeepCollectionEquality().hash(_badges),
      const DeepCollectionEquality().hash(_activity));

  /// Create a copy of ProfileBundle
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$ProfileBundleImplCopyWith<_$ProfileBundleImpl> get copyWith =>
      __$$ProfileBundleImplCopyWithImpl<_$ProfileBundleImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$ProfileBundleImplToJson(
      this,
    );
  }
}

abstract class _ProfileBundle implements ProfileBundle {
  const factory _ProfileBundle(
      {required final UserStats stats,
      required final List<UserBadge> badges,
      required final List<ProfileActivity> activity}) = _$ProfileBundleImpl;

  factory _ProfileBundle.fromJson(Map<String, dynamic> json) =
      _$ProfileBundleImpl.fromJson;

  @override
  UserStats get stats;
  @override
  List<UserBadge> get badges;
  @override
  List<ProfileActivity> get activity;

  /// Create a copy of ProfileBundle
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$ProfileBundleImplCopyWith<_$ProfileBundleImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
