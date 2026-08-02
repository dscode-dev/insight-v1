// coverage:ignore-file
// GENERATED CODE - DO NOT MODIFY BY HAND
// ignore_for_file: type=lint
// ignore_for_file: unused_element, deprecated_member_use, deprecated_member_use_from_same_package, use_function_type_syntax_for_parameters, unnecessary_const, avoid_init_to_null, invalid_override_different_default_values_named, prefer_expression_function_bodies, annotate_overrides, invalid_annotation_target, unnecessary_question_mark

part of 'realtime_event.dart';

// **************************************************************************
// FreezedGenerator
// **************************************************************************

T _$identity<T>(T value) => value;

final _privateConstructorUsedError = UnsupportedError(
    'It seems like you constructed your class using `MyClass._()`. This constructor is only meant to be used by freezed and you are not supposed to need it nor use it.\nPlease check the documentation here for more information: https://github.com/rrousselGit/freezed#adding-getters-and-methods-to-our-models');

RealtimeEvent _$RealtimeEventFromJson(Map<String, dynamic> json) {
  return _RealtimeEvent.fromJson(json);
}

/// @nodoc
mixin _$RealtimeEvent {
  String get eventId => throw _privateConstructorUsedError;
  EventType get eventType => throw _privateConstructorUsedError;
  String? get matchId => throw _privateConstructorUsedError;
  String? get regionCode => throw _privateConstructorUsedError;
  String? get tsIngest => throw _privateConstructorUsedError;
  Map<String, dynamic> get payload => throw _privateConstructorUsedError;
  String? get stream => throw _privateConstructorUsedError;

  /// Serializes this RealtimeEvent to a JSON map.
  Map<String, dynamic> toJson() => throw _privateConstructorUsedError;

  /// Create a copy of RealtimeEvent
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  $RealtimeEventCopyWith<RealtimeEvent> get copyWith =>
      throw _privateConstructorUsedError;
}

/// @nodoc
abstract class $RealtimeEventCopyWith<$Res> {
  factory $RealtimeEventCopyWith(
          RealtimeEvent value, $Res Function(RealtimeEvent) then) =
      _$RealtimeEventCopyWithImpl<$Res, RealtimeEvent>;
  @useResult
  $Res call(
      {String eventId,
      EventType eventType,
      String? matchId,
      String? regionCode,
      String? tsIngest,
      Map<String, dynamic> payload,
      String? stream});
}

/// @nodoc
class _$RealtimeEventCopyWithImpl<$Res, $Val extends RealtimeEvent>
    implements $RealtimeEventCopyWith<$Res> {
  _$RealtimeEventCopyWithImpl(this._value, this._then);

  // ignore: unused_field
  final $Val _value;
  // ignore: unused_field
  final $Res Function($Val) _then;

  /// Create a copy of RealtimeEvent
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? eventId = null,
    Object? eventType = null,
    Object? matchId = freezed,
    Object? regionCode = freezed,
    Object? tsIngest = freezed,
    Object? payload = null,
    Object? stream = freezed,
  }) {
    return _then(_value.copyWith(
      eventId: null == eventId
          ? _value.eventId
          : eventId // ignore: cast_nullable_to_non_nullable
              as String,
      eventType: null == eventType
          ? _value.eventType
          : eventType // ignore: cast_nullable_to_non_nullable
              as EventType,
      matchId: freezed == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String?,
      regionCode: freezed == regionCode
          ? _value.regionCode
          : regionCode // ignore: cast_nullable_to_non_nullable
              as String?,
      tsIngest: freezed == tsIngest
          ? _value.tsIngest
          : tsIngest // ignore: cast_nullable_to_non_nullable
              as String?,
      payload: null == payload
          ? _value.payload
          : payload // ignore: cast_nullable_to_non_nullable
              as Map<String, dynamic>,
      stream: freezed == stream
          ? _value.stream
          : stream // ignore: cast_nullable_to_non_nullable
              as String?,
    ) as $Val);
  }
}

/// @nodoc
abstract class _$$RealtimeEventImplCopyWith<$Res>
    implements $RealtimeEventCopyWith<$Res> {
  factory _$$RealtimeEventImplCopyWith(
          _$RealtimeEventImpl value, $Res Function(_$RealtimeEventImpl) then) =
      __$$RealtimeEventImplCopyWithImpl<$Res>;
  @override
  @useResult
  $Res call(
      {String eventId,
      EventType eventType,
      String? matchId,
      String? regionCode,
      String? tsIngest,
      Map<String, dynamic> payload,
      String? stream});
}

/// @nodoc
class __$$RealtimeEventImplCopyWithImpl<$Res>
    extends _$RealtimeEventCopyWithImpl<$Res, _$RealtimeEventImpl>
    implements _$$RealtimeEventImplCopyWith<$Res> {
  __$$RealtimeEventImplCopyWithImpl(
      _$RealtimeEventImpl _value, $Res Function(_$RealtimeEventImpl) _then)
      : super(_value, _then);

  /// Create a copy of RealtimeEvent
  /// with the given fields replaced by the non-null parameter values.
  @pragma('vm:prefer-inline')
  @override
  $Res call({
    Object? eventId = null,
    Object? eventType = null,
    Object? matchId = freezed,
    Object? regionCode = freezed,
    Object? tsIngest = freezed,
    Object? payload = null,
    Object? stream = freezed,
  }) {
    return _then(_$RealtimeEventImpl(
      eventId: null == eventId
          ? _value.eventId
          : eventId // ignore: cast_nullable_to_non_nullable
              as String,
      eventType: null == eventType
          ? _value.eventType
          : eventType // ignore: cast_nullable_to_non_nullable
              as EventType,
      matchId: freezed == matchId
          ? _value.matchId
          : matchId // ignore: cast_nullable_to_non_nullable
              as String?,
      regionCode: freezed == regionCode
          ? _value.regionCode
          : regionCode // ignore: cast_nullable_to_non_nullable
              as String?,
      tsIngest: freezed == tsIngest
          ? _value.tsIngest
          : tsIngest // ignore: cast_nullable_to_non_nullable
              as String?,
      payload: null == payload
          ? _value._payload
          : payload // ignore: cast_nullable_to_non_nullable
              as Map<String, dynamic>,
      stream: freezed == stream
          ? _value.stream
          : stream // ignore: cast_nullable_to_non_nullable
              as String?,
    ));
  }
}

/// @nodoc
@JsonSerializable()
class _$RealtimeEventImpl implements _RealtimeEvent {
  const _$RealtimeEventImpl(
      {required this.eventId,
      this.eventType = EventType.unknown,
      this.matchId,
      this.regionCode,
      this.tsIngest,
      final Map<String, dynamic> payload = const <String, dynamic>{},
      this.stream})
      : _payload = payload;

  factory _$RealtimeEventImpl.fromJson(Map<String, dynamic> json) =>
      _$$RealtimeEventImplFromJson(json);

  @override
  final String eventId;
  @override
  @JsonKey()
  final EventType eventType;
  @override
  final String? matchId;
  @override
  final String? regionCode;
  @override
  final String? tsIngest;
  final Map<String, dynamic> _payload;
  @override
  @JsonKey()
  Map<String, dynamic> get payload {
    if (_payload is EqualUnmodifiableMapView) return _payload;
    // ignore: implicit_dynamic_type
    return EqualUnmodifiableMapView(_payload);
  }

  @override
  final String? stream;

  @override
  String toString() {
    return 'RealtimeEvent(eventId: $eventId, eventType: $eventType, matchId: $matchId, regionCode: $regionCode, tsIngest: $tsIngest, payload: $payload, stream: $stream)';
  }

  @override
  bool operator ==(Object other) {
    return identical(this, other) ||
        (other.runtimeType == runtimeType &&
            other is _$RealtimeEventImpl &&
            (identical(other.eventId, eventId) || other.eventId == eventId) &&
            (identical(other.eventType, eventType) ||
                other.eventType == eventType) &&
            (identical(other.matchId, matchId) || other.matchId == matchId) &&
            (identical(other.regionCode, regionCode) ||
                other.regionCode == regionCode) &&
            (identical(other.tsIngest, tsIngest) ||
                other.tsIngest == tsIngest) &&
            const DeepCollectionEquality().equals(other._payload, _payload) &&
            (identical(other.stream, stream) || other.stream == stream));
  }

  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  int get hashCode => Object.hash(
      runtimeType,
      eventId,
      eventType,
      matchId,
      regionCode,
      tsIngest,
      const DeepCollectionEquality().hash(_payload),
      stream);

  /// Create a copy of RealtimeEvent
  /// with the given fields replaced by the non-null parameter values.
  @JsonKey(includeFromJson: false, includeToJson: false)
  @override
  @pragma('vm:prefer-inline')
  _$$RealtimeEventImplCopyWith<_$RealtimeEventImpl> get copyWith =>
      __$$RealtimeEventImplCopyWithImpl<_$RealtimeEventImpl>(this, _$identity);

  @override
  Map<String, dynamic> toJson() {
    return _$$RealtimeEventImplToJson(
      this,
    );
  }
}

abstract class _RealtimeEvent implements RealtimeEvent {
  const factory _RealtimeEvent(
      {required final String eventId,
      final EventType eventType,
      final String? matchId,
      final String? regionCode,
      final String? tsIngest,
      final Map<String, dynamic> payload,
      final String? stream}) = _$RealtimeEventImpl;

  factory _RealtimeEvent.fromJson(Map<String, dynamic> json) =
      _$RealtimeEventImpl.fromJson;

  @override
  String get eventId;
  @override
  EventType get eventType;
  @override
  String? get matchId;
  @override
  String? get regionCode;
  @override
  String? get tsIngest;
  @override
  Map<String, dynamic> get payload;
  @override
  String? get stream;

  /// Create a copy of RealtimeEvent
  /// with the given fields replaced by the non-null parameter values.
  @override
  @JsonKey(includeFromJson: false, includeToJson: false)
  _$$RealtimeEventImplCopyWith<_$RealtimeEventImpl> get copyWith =>
      throw _privateConstructorUsedError;
}
