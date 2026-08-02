// GENERATED CODE - DO NOT MODIFY BY HAND

part of 'realtime_event.dart';

// **************************************************************************
// JsonSerializableGenerator
// **************************************************************************

_$RealtimeEventImpl _$$RealtimeEventImplFromJson(Map<String, dynamic> json) =>
    _$RealtimeEventImpl(
      eventId: json['event_id'] as String,
      eventType: $enumDecodeNullable(_$EventTypeEnumMap, json['event_type']) ??
          EventType.unknown,
      matchId: json['match_id'] as String?,
      regionCode: json['region_code'] as String?,
      tsIngest: json['ts_ingest'] as String?,
      payload:
          json['payload'] as Map<String, dynamic>? ?? const <String, dynamic>{},
      stream: json['stream'] as String?,
    );

Map<String, dynamic> _$$RealtimeEventImplToJson(_$RealtimeEventImpl instance) =>
    <String, dynamic>{
      'event_id': instance.eventId,
      'event_type': _$EventTypeEnumMap[instance.eventType]!,
      if (instance.matchId case final value?) 'match_id': value,
      if (instance.regionCode case final value?) 'region_code': value,
      if (instance.tsIngest case final value?) 'ts_ingest': value,
      'payload': instance.payload,
      if (instance.stream case final value?) 'stream': value,
    };

const _$EventTypeEnumMap = {
  EventType.marketSnapshot: 'MARKET_SNAPSHOT',
  EventType.metricTick: 'METRIC_TICK',
  EventType.humanSignal: 'HUMAN_SIGNAL',
  EventType.agentInsight: 'AGENT_INSIGHT',
  EventType.notification: 'NOTIFICATION',
  EventType.unknown: 'unknown',
};
