import 'package:freezed_annotation/freezed_annotation.dart';

part 'realtime_event.freezed.dart';
part 'realtime_event.g.dart';

/// Known event types coming through Gateway's `/v1/realtime/sse` stream.
///
/// The wire field is `event_type` (snake_case via build.yaml field_rename).
/// Unknown types fall into `EventType.unknown` so a new server-side event
/// doesn't crash old clients — they just ignore it.
enum EventType {
  @JsonValue('MARKET_SNAPSHOT')
  marketSnapshot,
  @JsonValue('METRIC_TICK')
  metricTick,
  @JsonValue('HUMAN_SIGNAL')
  humanSignal,
  @JsonValue('AGENT_INSIGHT')
  agentInsight,
  @JsonValue('NOTIFICATION')
  notification,
  unknown,
}

/// Decoded SSE envelope. Gateway emits one per derived-stream entry; we
/// keep `payload` as raw JSON because each event type has its own shape
/// — screens that care decode it locally.
@freezed
class RealtimeEvent with _$RealtimeEvent {
  const factory RealtimeEvent({
    required String eventId,
    @Default(EventType.unknown) EventType eventType,
    String? matchId,
    String? regionCode,
    String? tsIngest,
    @Default(<String, dynamic>{}) Map<String, dynamic> payload,
    String? stream,
  }) = _RealtimeEvent;

  factory RealtimeEvent.fromJson(Map<String, dynamic> json) =>
      _$RealtimeEventFromJson(json);
}
