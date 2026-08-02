// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'discussion_thread.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

DiscussionDetail _$DiscussionDetailFromJson(Map<String, dynamic> json) {
  return _DiscussionDetail.fromJson(json);
}

/// @nodoc
mixin _$DiscussionDetail {
  String get id => throw _privateConstructorUsedError;
  String get title => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  String get communityId => throw _privateConstructorUsedError;
  String? get communityName => throw _privateConstructorUsedError;
  String? get communityHandle => throw _privateConstructorUsedError;
  String get authorId => throw _privateConstructorUsedError;
  String? get authorDisplayName => throw _privateConstructorUsedError;
  String? get authorInitials => throw _privateConstructorUsedError;
  String? get authorAccent => throw _privateConstructorUsedError;
  String? get matchId => throw _privateConstructorUsedError;
  int get replyCount => throw _privateConstructorUsedError;
  int get reactionCount => throw _privateConstructorUsedError;
  DateTime get createdAt => throw _privateConstructorUsedError;
  DateTime get lastActivityTs => throw _privateConstructorUsedError;

  /// Serializes this DiscussionDetail to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of DiscussionDetail
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DiscussionDetailCopyWith<DiscussionDetail> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DiscussionDetailCopyWith<$Res> {
  factory $DiscussionDetailCopyWith(
          DiscussionDetail value, $Res Function(DiscussionDetail) then) =
      _$DiscussionDetailCopyWithImpl<$Res, DiscussionDetail>;
  @useResult
  $Res call(
      {String id,
      String title,
      String body,
      String communityId,
      String? communityName,
      String? communityHandle,
      String authorId,
      String? authorDisplayName,
      String? authorInitials,
      String? authorAccent,
      String? matchId,
      int replyCount,
      int reactionCount,
      DateTime createdAt,
      DateTime lastActivityTs});
}

/// @nodoc
class _$DiscussionDetailCopyWithImpl<$Res, $Val extends DiscussionDetail>
    implements $DiscussionDetailCopyWith<$Res> {
  _$DiscussionDetailCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of DiscussionDetail
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? title = null,
    Object? body = null,
    Object? communityId = null,
    Object? communityName = freezed,
    Object? communityHandle = freezed,
    Object? authorId = null,
    Object? authorDisplayName = freezed,
    Object? authorInitials = freezed,
    Object? authorAccent = freezed,
    Object? matchId = freezed,
    Object? replyCount = null,
    Object? reactionCount = null,
    Object? createdAt = null,
    Object? lastActivityTs = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      title: null == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      communityId: null == communityId
          ? _value.communityId
          : communityId // ignore: cast_nullable_to_non_nullable
              as String,
      communityName: freezed == communityName
          ? _value.communityName
          : communityName // ignore: cast_nullable_to_non_nullable
              as String?,
      communityHandle: freezed == communityHandle
          ? _value.communityHandle
          : communityHandle // ignore: cast_nullable_to_non_nullable
              as String?,
      authorId: null == authorId
          ? _value.authorId
          : authorId // ignore: cast_nullable_to_non_nullable
              as String,
      authorDisplayName: freezed == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String?,
      authorInitials: freezed == authorInitials
          ? _value.authorInitials
          : authorInitials // ignore: cast_nullable_to_non_nullable
              as String?,
      authorAccent: freezed == authorAccent
          ? _value.authorAccent
          : authorAccent // ignore: cast_nullable_to_non_nullable
              as String?,
      matchId: freezed == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String?,
      replyCount: null == replyCount
          ? _value.replyCount
          : replyCount // ignore: cast_nullable_to_non_nullable
              as int,
      reactionCount: null == reactionCount
          ? _value.reactionCount
          : reactionCount // ignore: cast_nullable_to_non_nullable
              as int,
      createdAt: null == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime,
      lastActivityTs: null == lastActivityTs
          ? _value.lastActivityTs
          : lastActivityTs // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$DiscussionDetailImplCopyWith<$Res>
    implements $DiscussionDetailCopyWith<$Res> {
  factory _$$DiscussionDetailImplCopyWith(_$DiscussionDetailImpl value,
          $Res Function(_$DiscussionDetailImpl) then) =
      __$$DiscussionDetailImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String title,
      String body,
      String communityId,
      String? communityName,
      String? communityHandle,
      String authorId,
      String? authorDisplayName,
      String? authorInitials,
      String? authorAccent,
      String? matchId,
      int replyCount,
      int reactionCount,
      DateTime createdAt,
      DateTime lastActivityTs});
}

/// @nodoc
class __$$DiscussionDetailImplCopyWithImpl<$Res>
    extends _$DiscussionDetailCopyWithImpl<$Res, _$DiscussionDetailImpl>
    implements _$$DiscussionDetailImplCopyWith<$Res> {
  __$$DiscussionDetailImplCopyWithImpl(_$DiscussionDetailImpl _value,
      $Res Function(_$DiscussionDetailImpl) _then)
      : super(_value, _then);

  /// Create a copy of DiscussionDetail
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? title = null,
    Object? body = null,
    Object? communityId = null,
    Object? communityName = freezed,
    Object? communityHandle = freezed,
    Object? authorId = null,
    Object? authorDisplayName = freezed,
    Object? authorInitials = freezed,
    Object? authorAccent = freezed,
    Object? matchId = freezed,
    Object? replyCount = null,
    Object? reactionCount = null,
    Object? createdAt = null,
    Object? lastActivityTs = null,
  }) {
    return _then(_$DiscussionDetailImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      title: null == title
          ? _value.title
          : title // ignore: cast_nullable_to_non_nullable
              as String,
      body: null == body
          ? _value.body
          : body // ignore: cast_nullable_to_non_nullable
              as String,
      communityId: null == communityId
          ? _value.communityId
          : communityId // ignore: cast_nullable_to_non_nullable
              as String,
      communityName: freezed == communityName
          ? _value.communityName
          : communityName // ignore: cast_nullable_to_non_nullable
              as String?,
      communityHandle: freezed == communityHandle
          ? _value.communityHandle
          : communityHandle // ignore: cast_nullable_to_non_nullable
              as String?,
      authorId: null == authorId
          ? _value.authorId
          : authorId // ignore: cast_nullable_to_non_nullable
              as String,
      authorDisplayName: freezed == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String?,
      authorInitials: freezed == authorInitials
          ? _value.authorInitials
          : authorInitials // ignore: cast_nullable_to_non_nullable
              as String?,
      authorAccent: freezed == authorAccent
          ? _value.authorAccent
          : authorAccent // ignore: cast_nullable_to_non_nullable
              as String?,
      matchId: freezed == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String?,
      replyCount: null == replyCount
          ? _value.replyCount
          : replyCount // ignore: cast_nullable_to_non_nullable
              as int,
      reactionCount: null == reactionCount
          ? _value.reactionCount
          : reactionCount // ignore: cast_nullable_to_non_nullable
              as int,
      createdAt: null == createdAt
          ? _value.createdAt
          : createdAt // ignore: cast_nullable_to_non_nullable
              as DateTime,
      lastActivityTs: null == lastActivityTs
          ? _value.lastActivityTs
          : lastActivityTs // ignore: cast_nullable_to_non_nullable
              as DateTime,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$DiscussionDetailImpl implements _DiscussionDetail {
  const _$DiscussionDetailImpl(
      {required this.id,
      required this.title,
      required this.body,
      required this.communityId,
      this.communityName,
      this.communityHandle,
      required this.authorId,
      this.authorDisplayName,
      this.authorInitials,
      this.authorAccent,
      this.matchId,
      required this.replyCount,
      required this.reactionCount,
      required this.createdAt,
      required this.lastActivityTs});

  factory _$DiscussionDetailImpl.fromJson(Map<String, dynamic> json) =>
      _$$DiscussionDetailImplFromJson(json);

  @override
  final String id;
  @override
  final String title;
  @override
  final String body;
  @override
  final String communityId;
  @override
  final String? communityName;
  @override
  final String? communityHandle;
  @override
  final String authorId;
  @override
  final String? authorDisplayName;
  @override
  final String? authorInitials;
  @override
  final String? authorAccent;
  @override
  final String? matchId;
  @override
  final int replyCount;
  @override
  final int reactionCount;
  @override
  final DateTime createdAt;
  @override
  final DateTime lastActivityTs;

  @override
  String toString() {
    return 'DiscussionDetail(id: $id, title: $title, body: $body, communityId: $communityId, communityName: $communityName, communityHandle: $communityHandle, authorId: $authorId, authorDisplayName: $authorDisplayName, authorInitials: $authorInitials, authorAccent: $authorAccent, matchId: $matchId, replyCount: $replyCount, reactionCount: $reactionCount, createdAt: $createdAt, lastActivityTs: $lastActivityTs)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DiscussionDetailImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.title, title) || other.title == title) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.communityId, communityId) ||
                other.communityId == communityId) &&
            (identical(other.communityName, communityName) ||
                other.communityName == communityName) &&
            (identical(other.communityHandle, communityHandle) ||
                other.communityHandle == communityHandle) &&
            (identical(other.authorId, authorId) ||
                other.authorId == authorId) &&
            (identical(other.authorDisplayName, authorDisplayName) ||
                other.authorDisplayName == authorDisplayName) &&
            (identical(other.authorInitials, authorInitials) ||
                other.authorInitials == authorInitials) &&
            (identical(other.authorAccent, authorAccent) ||
                other.authorAccent == authorAccent) &&
            (identical(other.matchId, matchId) || other.matchId == matchId) &&
            (identical(other.replyCount, replyCount) ||
                other.replyCount == replyCount) &&
            (identical(other.reactionCount, reactionCount) ||
                other.reactionCount == reactionCount) &&
            (identical(other.createdAt, createdAt) ||
                other.createdAt == createdAt) &&
            (identical(other.lastActivityTs, lastActivityTs) ||
                other.lastActivityTs == lastActivityTs));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      id,
      title,
      body,
      communityId,
      communityName,
      communityHandle,
      authorId,
      authorDisplayName,
      authorInitials,
      authorAccent,
      matchId,
      replyCount,
      reactionCount,
      createdAt,
      lastActivityTs);

  /// Create a copy of DiscussionDetail
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DiscussionDetailImplCopyWith<_$DiscussionDetailImpl> get copyWith =>
      __$$DiscussionDetailImplCopyWithImpl<_$DiscussionDetailImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$DiscussionDetailImplToJson(
      this,
    );
  }
}

abstract class _DiscussionDetail implements DiscussionDetail {
  const factory _DiscussionDetail(
      {required final String id,
      required final String title,
      required final String body,
      required final String communityId,
      final String? communityName,
      final String? communityHandle,
      required final String authorId,
      final String? authorDisplayName,
      final String? authorInitials,
      final String? authorAccent,
      final String? matchId,
      required final int replyCount,
      required final int reactionCount,
      required final DateTime createdAt,
      required final DateTime lastActivityTs}) = _$DiscussionDetailImpl;

  factory _DiscussionDetail.fromJson(Map<String, dynamic> json) =
      _$DiscussionDetailImpl.fromJson;

  @override
  String get id;
  @override
  String get title;
  @override
  String get body;
  @override
  String get communityId;
  @override
  String? get communityName;
  @override
  String? get communityHandle;
  @override
  String get authorId;
  @override
  String? get authorDisplayName;
  @override
  String? get authorInitials;
  @override
  String? get authorAccent;
  @override
  String? get matchId;
  @override
  int get replyCount;
  @override
  int get reactionCount;
  @override
  DateTime get createdAt;
  @override
  DateTime get lastActivityTs;

  /// Create a copy of DiscussionDetail
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DiscussionDetailImplCopyWith<_$DiscussionDetailImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

DiscussionMessage _$DiscussionMessageFromJson(Map<String, dynamic> json) {
  return _DiscussionMessage.fromJson(json);
}

/// @nodoc
mixin _$DiscussionMessage {
  String get id => throw _privateConstructorUsedError;
  String get authorId => throw _privateConstructorUsedError;
  String? get authorDisplayName => throw _privateConstructorUsedError;
  String? get authorInitials => throw _privateConstructorUsedError;
  String? get authorAccent => throw _privateConstructorUsedError;
  String get body => throw _privateConstructorUsedError;
  DateTime get ts => throw _privateConstructorUsedError;

  /// Serializes this DiscussionMessage to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of DiscussionMessage
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DiscussionMessageCopyWith<DiscussionMessage> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DiscussionMessageCopyWith<$Res> {
  factory $DiscussionMessageCopyWith(
          DiscussionMessage value, $Res Function(DiscussionMessage) then) =
      _$DiscussionMessageCopyWithImpl<$Res, DiscussionMessage>;
  @useResult
  $Res call(
      {String id,
      String authorId,
      String? authorDisplayName,
      String? authorInitials,
      String? authorAccent,
      String body,
      DateTime ts});
}

/// @nodoc
class _$DiscussionMessageCopyWithImpl<$Res, $Val extends DiscussionMessage>
    implements $DiscussionMessageCopyWith<$Res> {
  _$DiscussionMessageCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of DiscussionMessage
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? authorId = null,
    Object? authorDisplayName = freezed,
    Object? authorInitials = freezed,
    Object? authorAccent = freezed,
    Object? body = null,
    Object? ts = null,
  }) {
    return _then(_value.copyWith(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      authorId: null == authorId
          ? _value.authorId
          : authorId // ignore: cast_nullable_to_non_nullable
              as String,
      authorDisplayName: freezed == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String?,
      authorInitials: freezed == authorInitials
          ? _value.authorInitials
          : authorInitials // ignore: cast_nullable_to_non_nullable
              as String?,
      authorAccent: freezed == authorAccent
          ? _value.authorAccent
          : authorAccent // ignore: cast_nullable_to_non_nullable
              as String?,
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
abstract class _$$DiscussionMessageImplCopyWith<$Res>
    implements $DiscussionMessageCopyWith<$Res> {
  factory _$$DiscussionMessageImplCopyWith(_$DiscussionMessageImpl value,
          $Res Function(_$DiscussionMessageImpl) then) =
      __$$DiscussionMessageImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String id,
      String authorId,
      String? authorDisplayName,
      String? authorInitials,
      String? authorAccent,
      String body,
      DateTime ts});
}

/// @nodoc
class __$$DiscussionMessageImplCopyWithImpl<$Res>
    extends _$DiscussionMessageCopyWithImpl<$Res, _$DiscussionMessageImpl>
    implements _$$DiscussionMessageImplCopyWith<$Res> {
  __$$DiscussionMessageImplCopyWithImpl(_$DiscussionMessageImpl _value,
      $Res Function(_$DiscussionMessageImpl) _then)
      : super(_value, _then);

  /// Create a copy of DiscussionMessage
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? id = null,
    Object? authorId = null,
    Object? authorDisplayName = freezed,
    Object? authorInitials = freezed,
    Object? authorAccent = freezed,
    Object? body = null,
    Object? ts = null,
  }) {
    return _then(_$DiscussionMessageImpl(
      id: null == id
          ? _value.id
          : id // ignore: cast_nullable_to_non_nullable
              as String,
      authorId: null == authorId
          ? _value.authorId
          : authorId // ignore: cast_nullable_to_non_nullable
              as String,
      authorDisplayName: freezed == authorDisplayName
          ? _value.authorDisplayName
          : authorDisplayName // ignore: cast_nullable_to_non_nullable
              as String?,
      authorInitials: freezed == authorInitials
          ? _value.authorInitials
          : authorInitials // ignore: cast_nullable_to_non_nullable
              as String?,
      authorAccent: freezed == authorAccent
          ? _value.authorAccent
          : authorAccent // ignore: cast_nullable_to_non_nullable
              as String?,
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
class _$DiscussionMessageImpl implements _DiscussionMessage {
  const _$DiscussionMessageImpl(
      {required this.id,
      required this.authorId,
      this.authorDisplayName,
      this.authorInitials,
      this.authorAccent,
      required this.body,
      required this.ts});

  factory _$DiscussionMessageImpl.fromJson(Map<String, dynamic> json) =>
      _$$DiscussionMessageImplFromJson(json);

  @override
  final String id;
  @override
  final String authorId;
  @override
  final String? authorDisplayName;
  @override
  final String? authorInitials;
  @override
  final String? authorAccent;
  @override
  final String body;
  @override
  final DateTime ts;

  @override
  String toString() {
    return 'DiscussionMessage(id: $id, authorId: $authorId, authorDisplayName: $authorDisplayName, authorInitials: $authorInitials, authorAccent: $authorAccent, body: $body, ts: $ts)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DiscussionMessageImpl &&
            (identical(other.id, id) || other.id == id) &&
            (identical(other.authorId, authorId) ||
                other.authorId == authorId) &&
            (identical(other.authorDisplayName, authorDisplayName) ||
                other.authorDisplayName == authorDisplayName) &&
            (identical(other.authorInitials, authorInitials) ||
                other.authorInitials == authorInitials) &&
            (identical(other.authorAccent, authorAccent) ||
                other.authorAccent == authorAccent) &&
            (identical(other.body, body) || other.body == body) &&
            (identical(other.ts, ts) || other.ts == ts));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(runtimeType, id, authorId, authorDisplayName,
      authorInitials, authorAccent, body, ts);

  /// Create a copy of DiscussionMessage
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DiscussionMessageImplCopyWith<_$DiscussionMessageImpl> get copyWith =>
      __$$DiscussionMessageImplCopyWithImpl<_$DiscussionMessageImpl>(
          this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$DiscussionMessageImplToJson(
      this,
    );
  }
}

abstract class _DiscussionMessage implements DiscussionMessage {
  const factory _DiscussionMessage(
      {required final String id,
      required final String authorId,
      final String? authorDisplayName,
      final String? authorInitials,
      final String? authorAccent,
      required final String body,
      required final DateTime ts}) = _$DiscussionMessageImpl;

  factory _DiscussionMessage.fromJson(Map<String, dynamic> json) =
      _$DiscussionMessageImpl.fromJson;

  @override
  String get id;
  @override
  String get authorId;
  @override
  String? get authorDisplayName;
  @override
  String? get authorInitials;
  @override
  String? get authorAccent;
  @override
  String get body;
  @override
  DateTime get ts;

  /// Create a copy of DiscussionMessage
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DiscussionMessageImplCopyWith<_$DiscussionMessageImpl> get copyWith =>
      throw _privateConstructorUsedError;
}

DiscussionMessagesPage _$DiscussionMessagesPageFromJson(
    Map<String, dynamic> json) {
  return _DiscussionMessagesPage.fromJson(json);
}

/// @nodoc
mixin _$DiscussionMessagesPage {
  List<DiscussionMessage> get messages => throw _privateConstructorUsedError;
  String? get nextCursor => throw _privateConstructorUsedError;

  /// Serializes this DiscussionMessagesPage to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of DiscussionMessagesPage
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $DiscussionMessagesPageCopyWith<DiscussionMessagesPage> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $DiscussionMessagesPageCopyWith<$Res> {
  factory $DiscussionMessagesPageCopyWith(DiscussionMessagesPage value,
          $Res Function(DiscussionMessagesPage) then) =
      _$DiscussionMessagesPageCopyWithImpl<$Res, DiscussionMessagesPage>;
  @useResult
  $Res call({List<DiscussionMessage> messages, String? nextCursor});
}

/// @nodoc
class _$DiscussionMessagesPageCopyWithImpl<$Res,
        $Val extends DiscussionMessagesPage>
    implements $DiscussionMessagesPageCopyWith<$Res> {
  _$DiscussionMessagesPageCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of DiscussionMessagesPage
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? messages = null,
    Object? nextCursor = freezed,
  }) {
    return _then(_value.copyWith(
      messages: null == messages
          ? _value.messages
          : messages // ignore: cast_nullable_to_non_nullable
              as List<DiscussionMessage>,
      nextCursor: freezed == nextCursor
          ? _value.nextCursor
          : nextCursor // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$DiscussionMessagesPageImplCopyWith<$Res>
    implements $DiscussionMessagesPageCopyWith<$Res> {
  factory _$$DiscussionMessagesPageImplCopyWith(
          _$DiscussionMessagesPageImpl value,
          $Res Function(_$DiscussionMessagesPageImpl) then) =
      __$$DiscussionMessagesPageImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call({List<DiscussionMessage> messages, String? nextCursor});
}

/// @nodoc
class __$$DiscussionMessagesPageImplCopyWithImpl<$Res>
    extends _$DiscussionMessagesPageCopyWithImpl<$Res,
        _$DiscussionMessagesPageImpl>
    implements _$$DiscussionMessagesPageImplCopyWith<$Res> {
  __$$DiscussionMessagesPageImplCopyWithImpl(
      _$DiscussionMessagesPageImpl _value,
      $Res Function(_$DiscussionMessagesPageImpl) _then)
      : super(_value, _then);

  /// Create a copy of DiscussionMessagesPage
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? messages = null,
    Object? nextCursor = freezed,
  }) {
    return _then(_$DiscussionMessagesPageImpl(
      messages: null == messages
          ? _value._messages
          : messages // ignore: cast_nullable_to_non_nullable
              as List<DiscussionMessage>,
      nextCursor: freezed == nextCursor
          ? _value.nextCursor
          : nextCursor // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$DiscussionMessagesPageImpl implements _DiscussionMessagesPage {
  const _$DiscussionMessagesPageImpl(
      {required final List<DiscussionMessage> messages, this.nextCursor})
      : _messages = messages;

  factory _$DiscussionMessagesPageImpl.fromJson(Map<String, dynamic> json) =>
      _$$DiscussionMessagesPageImplFromJson(json);

  final List<DiscussionMessage> _messages;
  @override
  List<DiscussionMessage> get messages {
    if (_messages is EqualUnmodifiableListView) return _messages;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableListView(_messages);
  }

  @override
  final String? nextCursor;

  @override
  String toString() {
    return 'DiscussionMessagesPage(messages: $messages, nextCursor: $nextCursor)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$DiscussionMessagesPageImpl &&
            const DeepCollectionEquality().equals(other._messages, _messages) &&
            (identical(other.nextCursor, nextCursor) ||
                other.nextCursor == nextCursor));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType, const DeepCollectionEquality().hash(_messages), nextCursor);

  /// Create a copy of DiscussionMessagesPage
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$DiscussionMessagesPageImplCopyWith<_$DiscussionMessagesPageImpl>
      get copyWith => __$$DiscussionMessagesPageImplCopyWithImpl<
          _$DiscussionMessagesPageImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$DiscussionMessagesPageImplToJson(
      this,
    );
  }
}

abstract class _DiscussionMessagesPage implements DiscussionMessagesPage {
  const factory _DiscussionMessagesPage(
      {required final List<DiscussionMessage> messages,
      final String? nextCursor}) = _$DiscussionMessagesPageImpl;

  factory _DiscussionMessagesPage.fromJson(Map<String, dynamic> json) =
      _$DiscussionMessagesPageImpl.fromJson;

  @override
  List<DiscussionMessage> get messages;
  @override
  String? get nextCursor;

  /// Create a copy of DiscussionMessagesPage
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$DiscussionMessagesPageImplCopyWith<_$DiscussionMessagesPageImpl>
      get copyWith => throw _privateConstructorUsedError;
}
