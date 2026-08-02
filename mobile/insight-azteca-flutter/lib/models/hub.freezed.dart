// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'hub.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

Community _$CommunityFromJson(Map<String, dynamic> json) {
  return _Community.fromJson(json);
}

/// @nodoc
mixin _$Community {
  String get id => throw _privateConstructorUsedError;
  String get name => throw _privateConstructorUsedError;
  String get handle => throw _privateConstructorUsedError; // "#tatica"
  String get accentColor => throw _privateConstructorUsedError;
  int get activeMembers => throw _privateConstructorUsedError;
  String? get description => throw _privateConstructorUsedError;

  /// Serializes this Community to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of Community
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CommunityCopyWith<Community> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CommunityCopyWith<$Res> {
  factory $CommunityCopyWith(Community value, $Res Function(Community) then) =
      _$CommunityCopyWithImpl<$Res, Community>;
  @useResult
  $Res call(
      {String id,
      String name,
      String handle,
      String accentColor,
      int activeMembers,
      String? description});
}

/// @nodoc
class _$CommunityCopyWithImpl<$Res, $Val extends Community>
    implements $CommunityCopyWith<$Res> {
  _$CommunityCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of Community
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? name = null,
    Object? handle = null,
    Object? accentColor = null,
    Object? activeMembers = null,
    Object? description = freezed,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      handle: null == handle
          ? _value.handle
          : handle // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      activeMembers: null == activeMembers
          ? _value.activeMembers
          : activeMembers // ignore: cast_nullable_to_non_nullable
              as int,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CommunityImplCopyWith<$Res>
    implements $CommunityCopyWith<$Res> {
  factory _$$CommunityImplCopyWith(
          _$CommunityImpl value, $Res Function(_$CommunityImpl) then) =
      __$$CommunityImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String name,
      String handle,
      String accentColor,
      int activeMembers,
      String? description});
}

/// @nodoc
class __$$CommunityImplCopyWithImpl<$Res>
    extends _$CommunityCopyWithImpl<$Res, _$CommunityImpl>
    implements _$$CommunityImplCopyWith<$Res> {
  __$$CommunityImplCopyWithImpl(
      _$CommunityImpl _value, $Res Function(_$CommunityImpl) _then)
      : super(_value, _then);

  /// Create a copy of Community
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? name = null,
    Object? handle = null,
    Object? accentColor = null,
    Object? activeMembers = null,
    Object? description = freezed,
  }) {
    return _then(_$CommunityImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      name: null == name
          ? _value.name
          : name // ignore: cast_nullable_to_non_nullable
              as String,
      handle: null == handle
          ? _value.handle
          : handle // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      activeMembers: null == activeMembers
          ? _value.activeMembers
          : activeMembers // ignore: cast_nullable_to_non_nullable
              as int,
      description: freezed == description
          ? _value.description
          : description // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$CommunityImpl implements _Community {
  const _$CommunityImpl(
      {required this.id,
      required this.name,
      required this.handle,
      required this.accentColor,
      required this.activeMembers,
      this.description});

  factory _$CommunityImpl.fromJson(Map<String, dynamic> json) =>
      _$$CommunityImplFromJson(json);

  @override
  final String id;
  @override
  final String name;
  @override
  final String handle;
// "#tatica"
  @override
  final String accentColor;
  @override
  final int activeMembers;
  @override
  final String? description;

  @override
  String toString() {
    return 'Community(id: $id, name: $name, handle: $handle, accentColor: $accentColor, activeMembers: $activeMembers, description: $description)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CommunityImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.name, name) || other.name == name) &&
            (identical(other.handle, handle) || other.handle == handle) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor) &&
            (identical(other.activeMembers, activeMembers) ||
                other.activeMembers == activeMembers) &&
            (identical(other.description, description) ||
                other.description == description));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType, id, name, handle, accentColor, activeMembers, description);

  /// Create a copy of Community
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CommunityImplCopyWith<_$CommunityImpl> get copyWith =>
      __$$CommunityImplCopyWithImpl<_$CommunityImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CommunityImplToJson(
      this,
    );
  }
}

abstract class _Community implements Community {
  const factory _Community(
      {required final String id,
      required final String name,
      required final String handle,
      required final String accentColor,
      required final int activeMembers,
      final String? description}) = _$CommunityImpl;

  factory _Community.fromJson(Map<String, dynamic> json) =
      _$CommunityImpl.fromJson;

  @override
  String get id;
  @override
  String get name;
  @override
  String get handle; // "#tatica"
  @override
  String get accentColor;
  @override
  int get activeMembers;
  @override
  String? get description;

  /// Create a copy of Community
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CommunityImplCopyWith<_$CommunityImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

Discussion _$DiscussionFromJson(Map<String, dynamic> json) {
  return _Discussion.fromJson(json);
}

/// @nodoc
mixin _$Discussion {
  String get id => throw _privateConstructorUsedError;
  String get communityHandle => throw _privateConstructorUsedError;
  String get authorDisplayName => throw _privateConstructorUsedError;
  String get authorAccent => throw _privateConstructorUsedError;
  String get authorInitials => throw _privateConstructorUsedError;
  String get title => throw _privateConstructorUsedError;
  String get snippet => throw _privateConstructorUsedError;
  int get replies => throw _privateConstructorUsedError;
  DateTime get lastActivityTs => throw _privateConstructorUsedError;

  /// Serializes this Discussion to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of Discussion
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DiscussionCopyWith<Discussion> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DiscussionCopyWith<$Res> {
  factory $DiscussionCopyWith(
          Discussion value, $Res Function(Discussion) then) =
      _$DiscussionCopyWithImpl<$Res, Discussion>;
  @useResult
  $Res call(
      {String id,
      String communityHandle,
      String authorDisplayName,
      String authorAccent,
      String authorInitials,
      String title,
      String snippet,
      int replies,
      DateTime lastActivityTs});
}

/// @nodoc
class _$DiscussionCopyWithImpl<$Res, $Val extends Discussion>
    implements $DiscussionCopyWith<$Res> {
  _$DiscussionCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of Discussion
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? communityHandle = null,
    Object? authorDisplayName = null,
    Object? authorAccent = null,
    Object? authorInitials = null,
    Object? title = null,
    Object? snippet = null,
    Object? replies = null,
    Object? lastActivityTs = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      communityHandle: null == communityHandle
          ? _value.communityHandle
          : communityHandle // ignore: cast_nullable_to_non_nullable
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
      title: null == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
              as String,
      snippet: null == snippet
          ? _value.snippet
          : snippet // ignore: cast_nullable_to_non_nullable
              as String,
      replies: null == replies
          ? _value.replies
          : replies // ignore: cast_nullable_to_non_nullable
              as int,
      lastActivityTs: null == lastActivityTs
          ? _value.lastActivityTs
          : lastActivityTs // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$DiscussionImplCopyWith<$Res>
    implements $DiscussionCopyWith<$Res> {
  factory _$$DiscussionImplCopyWith(
          _$DiscussionImpl value, $Res Function(_$DiscussionImpl) then) =
      __$$DiscussionImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String communityHandle,
      String authorDisplayName,
      String authorAccent,
      String authorInitials,
      String title,
      String snippet,
      int replies,
      DateTime lastActivityTs});
}

/// @nodoc
class __$$DiscussionImplCopyWithImpl<$Res>
    extends _$DiscussionCopyWithImpl<$Res, _$DiscussionImpl>
    implements _$$DiscussionImplCopyWith<$Res> {
  __$$DiscussionImplCopyWithImpl(
      _$DiscussionImpl _value, $Res Function(_$DiscussionImpl) _then)
      : super(_value, _then);

  /// Create a copy of Discussion
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? communityHandle = null,
    Object? authorDisplayName = null,
    Object? authorAccent = null,
    Object? authorInitials = null,
    Object? title = null,
    Object? snippet = null,
    Object? replies = null,
    Object? lastActivityTs = null,
  }) {
    return _then(_$DiscussionImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      communityHandle: null == communityHandle
          ? _value.communityHandle
          : communityHandle // ignore: cast_nullable_to_non_nullable
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
      title: null == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
              as String,
      snippet: null == snippet
          ? _value.snippet
          : snippet // ignore: cast_nullable_to_non_nullable
              as String,
      replies: null == replies
          ? _value.replies
          : replies // ignore: cast_nullable_to_non_nullable
              as int,
      lastActivityTs: null == lastActivityTs
          ? _value.lastActivityTs
          : lastActivityTs // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$DiscussionImpl implements _Discussion {
  const _$DiscussionImpl(
      {required this.id,
      required this.communityHandle,
      required this.authorDisplayName,
      required this.authorAccent,
      required this.authorInitials,
      required this.title,
      required this.snippet,
      required this.replies,
      required this.lastActivityTs});

  factory _$DiscussionImpl.fromJson(Map<String, dynamic> json) =>
      _$$DiscussionImplFromJson(json);

  @override
  final String id;
  @override
  final String communityHandle;
  @override
  final String authorDisplayName;
  @override
  final String authorAccent;
  @override
  final String authorInitials;
  @override
  final String title;
  @override
  final String snippet;
  @override
  final int replies;
  @override
  final DateTime lastActivityTs;

  @override
  String toString() {
    return 'Discussion(id: $id, communityHandle: $communityHandle, authorDisplayName: $authorDisplayName, authorAccent: $authorAccent, authorInitials: $authorInitials, title: $title, snippet: $snippet, replies: $replies, lastActivityTs: $lastActivityTs)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DiscussionImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.communityHandle, communityHandle) ||
                other.communityHandle == communityHandle) &&
            (identical(other.authorDisplayName, authorDisplayName) ||
                other.authorDisplayName == authorDisplayName) &&
            (identical(other.authorAccent, authorAccent) ||
                other.authorAccent == authorAccent) &&
            (identical(other.authorInitials, authorInitials) ||
                other.authorInitials == authorInitials) &&
            (identical(other.title, title) || other.title == title) &&
            (identical(other.snippet, snippet) || other.snippet == snippet) &&
            (identical(other.replies, replies) || other.replies == replies) &&
            (identical(other.lastActivityTs, lastActivityTs) ||
                other.lastActivityTs == lastActivityTs));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      id,
      communityHandle,
      authorDisplayName,
      authorAccent,
      authorInitials,
      title,
      snippet,
      replies,
      lastActivityTs);

  /// Create a copy of Discussion
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DiscussionImplCopyWith<_$DiscussionImpl> get copyWith =>
      __$$DiscussionImplCopyWithImpl<_$DiscussionImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$DiscussionImplToJson(
      this,
    );
  }
}

abstract class _Discussion implements Discussion {
  const factory _Discussion(
      {required final String id,
      required final String communityHandle,
      required final String authorDisplayName,
      required final String authorAccent,
      required final String authorInitials,
      required final String title,
      required final String snippet,
      required final int replies,
      required final DateTime lastActivityTs}) = _$DiscussionImpl;

  factory _Discussion.fromJson(Map<String, dynamic> json) =
      _$DiscussionImpl.fromJson;

  @override
  String get id;
  @override
  String get communityHandle;
  @override
  String get authorDisplayName;
  @override
  String get authorAccent;
  @override
  String get authorInitials;
  @override
  String get title;
  @override
  String get snippet;
  @override
  int get replies;
  @override
  DateTime get lastActivityTs;

  /// Create a copy of Discussion
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DiscussionImplCopyWith<_$DiscussionImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

Tipster _$TipsterFromJson(Map<String, dynamic> json) {
  return _Tipster.fromJson(json);
}

/// @nodoc
mixin _$Tipster {
  String get id => throw _privateConstructorUsedError;
  String get displayName => throw _privateConstructorUsedError;
  String get username => throw _privateConstructorUsedError;
  String get accentColor => throw _privateConstructorUsedError;
  String get initials => throw _privateConstructorUsedError;
  double get accuracy => throw _privateConstructorUsedError; // 0..1
  int get signals => throw _privateConstructorUsedError;
  String get tier => throw _privateConstructorUsedError;

  /// Serializes this Tipster to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of Tipster
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $TipsterCopyWith<Tipster> get copyWith => throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $TipsterCopyWith<$Res> {
  factory $TipsterCopyWith(Tipster value, $Res Function(Tipster) then) =
      _$TipsterCopyWithImpl<$Res, Tipster>;
  @useResult
  $Res call(
      {String id,
      String displayName,
      String username,
      String accentColor,
      String initials,
      double accuracy,
      int signals,
      String tier});
}

/// @nodoc
class _$TipsterCopyWithImpl<$Res, $Val extends Tipster>
    implements $TipsterCopyWith<$Res> {
  _$TipsterCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of Tipster
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? displayName = null,
    Object? username = null,
    Object? accentColor = null,
    Object? initials = null,
    Object? accuracy = null,
    Object? signals = null,
    Object? tier = null,
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
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      initials: null == initials
          ? _value.initials
          : initials // ignore: cast_nullable_to_non_nullable
              as String,
      accuracy: null == accuracy
          ? _value.accuracy
          : accuracy // ignore: cast_nullable_to_non_nullable
              as double,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as int,
      tier: null == tier
          ? _value.tier
          : tier // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$TipsterImplCopyWith<$Res> implements $TipsterCopyWith<$Res> {
  factory _$$TipsterImplCopyWith(
          _$TipsterImpl value, $Res Function(_$TipsterImpl) then) =
      __$$TipsterImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String displayName,
      String username,
      String accentColor,
      String initials,
      double accuracy,
      int signals,
      String tier});
}

/// @nodoc
class __$$TipsterImplCopyWithImpl<$Res>
    extends _$TipsterCopyWithImpl<$Res, _$TipsterImpl>
    implements _$$TipsterImplCopyWith<$Res> {
  __$$TipsterImplCopyWithImpl(
      _$TipsterImpl _value, $Res Function(_$TipsterImpl) _then)
      : super(_value, _then);

  /// Create a copy of Tipster
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? displayName = null,
    Object? username = null,
    Object? accentColor = null,
    Object? initials = null,
    Object? accuracy = null,
    Object? signals = null,
    Object? tier = null,
  }) {
    return _then(_$TipsterImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      initials: null == initials
          ? _value.initials
          : initials // ignore: cast_nullable_to_non_nullable
              as String,
      accuracy: null == accuracy
          ? _value.accuracy
          : accuracy // ignore: cast_nullable_to_non_nullable
              as double,
      signals: null == signals
          ? _value.signals
          : signals // ignore: cast_nullable_to_non_nullable
              as int,
      tier: null == tier
          ? _value.tier
          : tier // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$TipsterImpl implements _Tipster {
  const _$TipsterImpl(
      {required this.id,
      required this.displayName,
      required this.username,
      required this.accentColor,
      required this.initials,
      required this.accuracy,
      required this.signals,
      required this.tier});

  factory _$TipsterImpl.fromJson(Map<String, dynamic> json) =>
      _$$TipsterImplFromJson(json);

  @override
  final String id;
  @override
  final String displayName;
  @override
  final String username;
  @override
  final String accentColor;
  @override
  final String initials;
  @override
  final double accuracy;
// 0..1
  @override
  final int signals;
  @override
  final String tier;

  @override
  String toString() {
    return 'Tipster(id: $id, displayName: $displayName, username: $username, accentColor: $accentColor, initials: $initials, accuracy: $accuracy, signals: $signals, tier: $tier)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$TipsterImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.displayName, displayName) ||
                other.displayName == displayName) &&
            (identical(other.username, username) ||
                other.username == username) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor) &&
            (identical(other.initials, initials) ||
                other.initials == initials) &&
            (identical(other.accuracy, accuracy) ||
                other.accuracy == accuracy) &&
            (identical(other.signals, signals) || other.signals == signals) &&
            (identical(other.tier, tier) || other.tier == tier));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, displayName, username,
      accentColor, initials, accuracy, signals, tier);

  /// Create a copy of Tipster
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$TipsterImplCopyWith<_$TipsterImpl> get copyWith =>
      __$$TipsterImplCopyWithImpl<_$TipsterImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$TipsterImplToJson(
      this,
    );
  }
}

abstract class _Tipster implements Tipster {
  const factory _Tipster(
      {required final String id,
      required final String displayName,
      required final String username,
      required final String accentColor,
      required final String initials,
      required final double accuracy,
      required final int signals,
      required final String tier}) = _$TipsterImpl;

  factory _Tipster.fromJson(Map<String, dynamic> json) = _$TipsterImpl.fromJson;

  @override
  String get id;
  @override
  String get displayName;
  @override
  String get username;
  @override
  String get accentColor;
  @override
  String get initials;
  @override
  double get accuracy; // 0..1
  @override
  int get signals;
  @override
  String get tier;

  /// Create a copy of Tipster
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$TipsterImplCopyWith<_$TipsterImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

HubBundle _$HubBundleFromJson(Map<String, dynamic> json) {
  return _HubBundle.fromJson(json);
}

/// @nodoc
mixin _$HubBundle {
  List<Community> get communities => throw _privateConstructorUsedError;
  List<Tipster> get tipsters => throw _privateConstructorUsedError;
  List<Discussion> get discussions => throw _privateConstructorUsedError;

  /// Serializes this HubBundle to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of HubBundle
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $HubBundleCopyWith<HubBundle> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $HubBundleCopyWith<$Res> {
  factory $HubBundleCopyWith(HubBundle value, $Res Function(HubBundle) then) =
      _$HubBundleCopyWithImpl<$Res, HubBundle>;
  @useResult
  $Res call(
      {List<Community> communities,
      List<Tipster> tipsters,
      List<Discussion> discussions});
}

/// @nodoc
class _$HubBundleCopyWithImpl<$Res, $Val extends HubBundle>
    implements $HubBundleCopyWith<$Res> {
  _$HubBundleCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of HubBundle
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? communities = null,
    Object? tipsters = null,
    Object? discussions = null,
  }) {
    return _then(_value.copyWith(
      communities: null == communities
          ? _value.communities
          : communities // ignore: cast_nullable_to_non_nullable
              as List<Community>,
      tipsters: null == tipsters
          ? _value.tipsters
          : tipsters // ignore: cast_nullable_to_non_nullable
              as List<Tipster>,
      discussions: null == discussions
          ? _value.discussions
          : discussions // ignore: cast_nullable_to_non_nullable
              as List<Discussion>,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$HubBundleImplCopyWith<$Res>
    implements $HubBundleCopyWith<$Res> {
  factory _$$HubBundleImplCopyWith(
          _$HubBundleImpl value, $Res Function(_$HubBundleImpl) then) =
      __$$HubBundleImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {List<Community> communities,
      List<Tipster> tipsters,
      List<Discussion> discussions});
}

/// @nodoc
class __$$HubBundleImplCopyWithImpl<$Res>
    extends _$HubBundleCopyWithImpl<$Res, _$HubBundleImpl>
    implements _$$HubBundleImplCopyWith<$Res> {
  __$$HubBundleImplCopyWithImpl(
      _$HubBundleImpl _value, $Res Function(_$HubBundleImpl) _then)
      : super(_value, _then);

  /// Create a copy of HubBundle
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? communities = null,
    Object? tipsters = null,
    Object? discussions = null,
  }) {
    return _then(_$HubBundleImpl(
      communities: null == communities
          ? _value._communities
          : communities // ignore: cast_nullable_to_non_nullable
              as List<Community>,
      tipsters: null == tipsters
          ? _value._tipsters
          : tipsters // ignore: cast_nullable_to_non_nullable
              as List<Tipster>,
      discussions: null == discussions
          ? _value._discussions
          : discussions // ignore: cast_nullable_to_non_nullable
              as List<Discussion>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$HubBundleImpl implements _HubBundle {
  const _$HubBundleImpl(
      {required final List<Community> communities,
      required final List<Tipster> tipsters,
      required final List<Discussion> discussions})
      : _communities = communities,
        _tipsters = tipsters,
        _discussions = discussions;

  factory _$HubBundleImpl.fromJson(Map<String, dynamic> json) =>
      _$$HubBundleImplFromJson(json);

  final List<Community> _communities;
  @override
  List<Community> get communities {
    if (_communities is EqualUnmodifiableListView) return _communities;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_communities);
  }

  final List<Tipster> _tipsters;
  @override
  List<Tipster> get tipsters {
    if (_tipsters is EqualUnmodifiableListView) return _tipsters;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_tipsters);
  }

  final List<Discussion> _discussions;
  @override
  List<Discussion> get discussions {
    if (_discussions is EqualUnmodifiableListView) return _discussions;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_discussions);
  }

  @override
  String toString() {
    return 'HubBundle(communities: $communities, tipsters: $tipsters, discussions: $discussions)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$HubBundleImpl &&
            const DeepCollectionEquality()
                .equals(other._communities, _communities) &&
            const DeepCollectionEquality().equals(other._tipsters, _tipsters) &&
            const DeepCollectionEquality()
                .equals(other._discussions, _discussions));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      const DeepCollectionEquality().hash(_communities),
      const DeepCollectionEquality().hash(_tipsters),
      const DeepCollectionEquality().hash(_discussions));

  /// Create a copy of HubBundle
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$HubBundleImplCopyWith<_$HubBundleImpl> get copyWith =>
      __$$HubBundleImplCopyWithImpl<_$HubBundleImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$HubBundleImplToJson(
      this,
    );
  }
}

abstract class _HubBundle implements HubBundle {
  const factory _HubBundle(
      {required final List<Community> communities,
      required final List<Tipster> tipsters,
      required final List<Discussion> discussions}) = _$HubBundleImpl;

  factory _HubBundle.fromJson(Map<String, dynamic> json) =
      _$HubBundleImpl.fromJson;

  @override
  List<Community> get communities;
  @override
  List<Tipster> get tipsters;
  @override
  List<Discussion> get discussions;

  /// Create a copy of HubBundle
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$HubBundleImplCopyWith<_$HubBundleImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

CommunityMember _$CommunityMemberFromJson(Map<String, dynamic> json) {
  return _CommunityMember.fromJson(json);
}

/// @nodoc
mixin _$CommunityMember {
  String get id => throw _privateConstructorUsedError;
  String get displayName => throw _privateConstructorUsedError;
  String get username => throw _privateConstructorUsedError;
  String get initials => throw _privateConstructorUsedError;
  String get accentColor => throw _privateConstructorUsedError;
  String get roleLabel => throw _privateConstructorUsedError;

  /// Serializes this CommunityMember to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of CommunityMember
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CommunityMemberCopyWith<CommunityMember> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CommunityMemberCopyWith<$Res> {
  factory $CommunityMemberCopyWith(
          CommunityMember value, $Res Function(CommunityMember) then) =
      _$CommunityMemberCopyWithImpl<$Res, CommunityMember>;
  @useResult
  $Res call(
      {String id,
      String displayName,
      String username,
      String initials,
      String accentColor,
      String roleLabel});
}

/// @nodoc
class _$CommunityMemberCopyWithImpl<$Res, $Val extends CommunityMember>
    implements $CommunityMemberCopyWith<$Res> {
  _$CommunityMemberCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of CommunityMember
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? displayName = null,
    Object? username = null,
    Object? initials = null,
    Object? accentColor = null,
    Object? roleLabel = null,
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
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      initials: null == initials
          ? _value.initials
          : initials // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      roleLabel: null == roleLabel
          ? _value.roleLabel
          : roleLabel // ignore: cast_nullable_to_non_nullable
              as String,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$CommunityMemberImplCopyWith<$Res>
    implements $CommunityMemberCopyWith<$Res> {
  factory _$$CommunityMemberImplCopyWith(_$CommunityMemberImpl value,
          $Res Function(_$CommunityMemberImpl) then) =
      __$$CommunityMemberImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String displayName,
      String username,
      String initials,
      String accentColor,
      String roleLabel});
}

/// @nodoc
class __$$CommunityMemberImplCopyWithImpl<$Res>
    extends _$CommunityMemberCopyWithImpl<$Res, _$CommunityMemberImpl>
    implements _$$CommunityMemberImplCopyWith<$Res> {
  __$$CommunityMemberImplCopyWithImpl(
      _$CommunityMemberImpl _value, $Res Function(_$CommunityMemberImpl) _then)
      : super(_value, _then);

  /// Create a copy of CommunityMember
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? displayName = null,
    Object? username = null,
    Object? initials = null,
    Object? accentColor = null,
    Object? roleLabel = null,
  }) {
    return _then(_$CommunityMemberImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      displayName: null == displayName
          ? _value.displayName
          : displayName // ignore: cast_nullable_to_non_nullable
              as String,
      username: null == username
          ? _value.username
          : username // ignore: cast_nullable_to_non_nullable
              as String,
      initials: null == initials
          ? _value.initials
          : initials // ignore: cast_nullable_to_non_nullable
              as String,
      accentColor: null == accentColor
          ? _value.accentColor
          : accentColor // ignore: cast_nullable_to_non_nullable
              as String,
      roleLabel: null == roleLabel
          ? _value.roleLabel
          : roleLabel // ignore: cast_nullable_to_non_nullable
              as String,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$CommunityMemberImpl implements _CommunityMember {
  const _$CommunityMemberImpl(
      {required this.id,
      required this.displayName,
      required this.username,
      required this.initials,
      required this.accentColor,
      required this.roleLabel});

  factory _$CommunityMemberImpl.fromJson(Map<String, dynamic> json) =>
      _$$CommunityMemberImplFromJson(json);

  @override
  final String id;
  @override
  final String displayName;
  @override
  final String username;
  @override
  final String initials;
  @override
  final String accentColor;
  @override
  final String roleLabel;

  @override
  String toString() {
    return 'CommunityMember(id: $id, displayName: $displayName, username: $username, initials: $initials, accentColor: $accentColor, roleLabel: $roleLabel)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CommunityMemberImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.displayName, displayName) ||
                other.displayName == displayName) &&
            (identical(other.username, username) ||
                other.username == username) &&
            (identical(other.initials, initials) ||
                other.initials == initials) &&
            (identical(other.accentColor, accentColor) ||
                other.accentColor == accentColor) &&
            (identical(other.roleLabel, roleLabel) ||
                other.roleLabel == roleLabel));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType, id, displayName, username, initials, accentColor, roleLabel);

  /// Create a copy of CommunityMember
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CommunityMemberImplCopyWith<_$CommunityMemberImpl> get copyWith =>
      __$$CommunityMemberImplCopyWithImpl<_$CommunityMemberImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CommunityMemberImplToJson(
      this,
    );
  }
}

abstract class _CommunityMember implements CommunityMember {
  const factory _CommunityMember(
      {required final String id,
      required final String displayName,
      required final String username,
      required final String initials,
      required final String accentColor,
      required final String roleLabel}) = _$CommunityMemberImpl;

  factory _CommunityMember.fromJson(Map<String, dynamic> json) =
      _$CommunityMemberImpl.fromJson;

  @override
  String get id;
  @override
  String get displayName;
  @override
  String get username;
  @override
  String get initials;
  @override
  String get accentColor;
  @override
  String get roleLabel;

  /// Create a copy of CommunityMember
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CommunityMemberImplCopyWith<_$CommunityMemberImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

CommunityDetail _$CommunityDetailFromJson(Map<String, dynamic> json) {
  return _CommunityDetail.fromJson(json);
}

/// @nodoc
mixin _$CommunityDetail {
  Community get community => throw _privateConstructorUsedError;
  List<Discussion> get discussions => throw _privateConstructorUsedError;
  List<CommunityMember> get members => throw _privateConstructorUsedError;

  /// Serializes this CommunityDetail to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of CommunityDetail
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $CommunityDetailCopyWith<CommunityDetail> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $CommunityDetailCopyWith<$Res> {
  factory $CommunityDetailCopyWith(
          CommunityDetail value, $Res Function(CommunityDetail) then) =
      _$CommunityDetailCopyWithImpl<$Res, CommunityDetail>;
  @useResult
  $Res call(
      {Community community,
      List<Discussion> discussions,
      List<CommunityMember> members});

  $CommunityCopyWith<$Res> get community;
}

/// @nodoc
class _$CommunityDetailCopyWithImpl<$Res, $Val extends CommunityDetail>
    implements $CommunityDetailCopyWith<$Res> {
  _$CommunityDetailCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of CommunityDetail
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? community = null,
    Object? discussions = null,
    Object? members = null,
  }) {
    return _then(_value.copyWith(
      community: null == community
          ? _value.community
          : community // ignore: cast_nullable_to_non_nullable
              as Community,
      discussions: null == discussions
          ? _value.discussions
          : discussions // ignore: cast_nullable_to_non_nullable
              as List<Discussion>,
      members: null == members
          ? _value.members
          : members // ignore: cast_nullable_to_non_nullable
              as List<CommunityMember>,
    ) as $Val);
  }

  /// Create a copy of CommunityDetail
  /// with the given fields replaced by the non-null parameter values.
  @override
  @pragma('vm:prefer-inline')
  $CommunityCopyWith<$Res> get community {
    return $CommunityCopyWith<$Res>(_value.community, (value) {
      return _then(_value.copyWith(community: value) as $Val);
    });
  }
}

/// @nodoc
abstract class _$$CommunityDetailImplCopyWith<$Res>
    implements $CommunityDetailCopyWith<$Res> {
  factory _$$CommunityDetailImplCopyWith(_$CommunityDetailImpl value,
          $Res Function(_$CommunityDetailImpl) then) =
      __$$CommunityDetailImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {Community community,
      List<Discussion> discussions,
      List<CommunityMember> members});

  @override
  $CommunityCopyWith<$Res> get community;
}

/// @nodoc
class __$$CommunityDetailImplCopyWithImpl<$Res>
    extends _$CommunityDetailCopyWithImpl<$Res, _$CommunityDetailImpl>
    implements _$$CommunityDetailImplCopyWith<$Res> {
  __$$CommunityDetailImplCopyWithImpl(
      _$CommunityDetailImpl _value, $Res Function(_$CommunityDetailImpl) _then)
      : super(_value, _then);

  /// Create a copy of CommunityDetail
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? community = null,
    Object? discussions = null,
    Object? members = null,
  }) {
    return _then(_$CommunityDetailImpl(
      community: null == community
          ? _value.community
          : community // ignore: cast_nullable_to_non_nullable
              as Community,
      discussions: null == discussions
          ? _value._discussions
          : discussions // ignore: cast_nullable_to_non_nullable
              as List<Discussion>,
      members: null == members
          ? _value._members
          : members // ignore: cast_nullable_to_non_nullable
              as List<CommunityMember>,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$CommunityDetailImpl implements _CommunityDetail {
  const _$CommunityDetailImpl(
      {required this.community,
      required final List<Discussion> discussions,
      required final List<CommunityMember> members})
      : _discussions = discussions,
        _members = members;

  factory _$CommunityDetailImpl.fromJson(Map<String, dynamic> json) =>
      _$$CommunityDetailImplFromJson(json);

  @override
  final Community community;
  final List<Discussion> _discussions;
  @override
  List<Discussion> get discussions {
    if (_discussions is EqualUnmodifiableListView) return _discussions;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_discussions);
  }

  final List<CommunityMember> _members;
  @override
  List<CommunityMember> get members {
    if (_members is EqualUnmodifiableListView) return _members;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_members);
  }

  @override
  String toString() {
    return 'CommunityDetail(community: $community, discussions: $discussions, members: $members)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$CommunityDetailImpl &&
            (identical(other.community, community) ||
                other.community == community) &&
            const DeepCollectionEquality()
                .equals(other._discussions, _discussions) &&
            const DeepCollectionEquality().equals(other._members, _members));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      community,
      const DeepCollectionEquality().hash(_discussions),
      const DeepCollectionEquality().hash(_members));

  /// Create a copy of CommunityDetail
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$CommunityDetailImplCopyWith<_$CommunityDetailImpl> get copyWith =>
      __$$CommunityDetailImplCopyWithImpl<_$CommunityDetailImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$CommunityDetailImplToJson(
      this,
    );
  }
}

abstract class _CommunityDetail implements CommunityDetail {
  const factory _CommunityDetail(
      {required final Community community,
      required final List<Discussion> discussions,
      required final List<CommunityMember> members}) = _$CommunityDetailImpl;

  factory _CommunityDetail.fromJson(Map<String, dynamic> json) =
      _$CommunityDetailImpl.fromJson;

  @override
  Community get community;
  @override
  List<Discussion> get discussions;
  @override
  List<CommunityMember> get members;

  /// Create a copy of CommunityDetail
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$CommunityDetailImplCopyWith<_$CommunityDetailImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
