import 'package:freezed_annotation/freezed_annotation.dart';

part 'insight.freezed.dart';
part 'insight.g.dart';

/// Pundit agent identifier — drives the lateral stripe colour in the feed.
enum AgentId {
  @JsonValue('scout')
  scout,
  @JsonValue('pulse')
  pulse,
  @JsonValue('momentum')
  momentum,
  @JsonValue('stats')
  stats,
  @JsonValue('history')
  history,
}

extension AgentIdX on AgentId {
  String get labelPtBr {
    switch (this) {
      case AgentId.scout:
        return 'Scout AI';
      case AgentId.pulse:
        return 'Pulse AI';
      case AgentId.momentum:
        return 'Momentum AI';
      case AgentId.stats:
        return 'Stats AI';
      case AgentId.history:
        return 'History AI';
    }
  }
}

enum AgentInsightKind {
  @JsonValue('tactical_shift')
  tacticalShift,
  @JsonValue('pressing_pattern')
  pressingPattern,
  @JsonValue('sentiment_swing')
  sentimentSwing,
  @JsonValue('crowd_polarisation')
  crowdPolarisation,
  @JsonValue('momentum_shift')
  momentumShift,
  @JsonValue('shot_pressure_reversal')
  shotPressureReversal,
  @JsonValue('threshold_cross')
  thresholdCross,
  @JsonValue('rolling_anomaly')
  rollingAnomaly,
  @JsonValue('historical_context')
  historicalContext,
  @JsonValue('rare_event')
  rareEvent,
}

/// Standalone agent insight returned by `/v1/insights/match/{id}` (the
/// Gateway → Pundit proxy). The unified feed embeds these as posts with
/// kind="agent_insight"; this model is for the per-match strip surface.
@freezed
class AgentInsight with _$AgentInsight {
  const factory AgentInsight({
    required String insightId,
    required AgentId agentId,
    required AgentInsightKind insightKind,
    required String matchId,
    required String headline,
    @Default('') String body,
    required double confidence,
    int? minute,
    @Default(<String>[]) List<String> refs,
    @Default(<String, dynamic>{}) Map<String, dynamic> metrics,
    required DateTime createdAt,
  }) = _AgentInsight;

  factory AgentInsight.fromJson(Map<String, dynamic> json) =>
      _$AgentInsightFromJson(json);
}
